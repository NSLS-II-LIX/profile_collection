import uuid
import time,os
from enum import Enum
from ophyd import (EpicsSignal, EpicsSignalRO, Device, Component as Cpt)
from collections import ChainMap
from ophyd import DeviceStatus
from bluesky.preprocessors import (monitor_during_decorator, run_decorator,
                                   stage_decorator, subs_decorator)
from bluesky.plan_stubs import (complete, kickoff, collect, monitor, unmonitor,
                                trigger_and_read)
from bluesky.callbacks import LivePlot

class HPLCStatus(str, Enum):
    idle = "idle"
    waiting_injected = "waiting_injected"
    waiting_done = "waiting_done"

class HPLC(Device):
    ready = Cpt(EpicsSignal, 'out')
    injected = Cpt(EpicsSignalRO, 'in1')
    done = Cpt(EpicsSignalRO, 'in2')
    bypass = Cpt(EpicsSignal, '_bypass')
    
    def __init__(self, *args, read_filepath, write_filepath, **kwargs):
        self.hplc_status = HPLCStatus.idle
        self._injected_status = None
        self._done_status = None
        self._bypass_status = None
        self._resource = None
        self._read_filepath = read_filepath
        self._write_filepath = write_filepath
        super().__init__(*args, **kwargs)

    def stage(self):
        self.injected.subscribe(self._injected_changed)
        self.done.subscribe(self._done_changed)
        self.bypass.subscribe(self._bypass_changed)

    def unstage(self):
        self.injected.clear_sub(self._injected_changed)
        self.done.clear_sub(self._done_changed)
        self.bypass.clear_sub(self._bypass_changed)
        self._injected_status = None
        self._done_status = None
        self._bypass_status = None
        # self._resource = None

    def kickoff(self):
        """
        Set 'ready' to True and return a status object tied to 'injected'.
        """
        self.ready.set(1)
        self.hplc_status = HPLCStatus.waiting_injected
        self._injected_status = DeviceStatus(self.injected)
        self._done_status = DeviceStatus(self.done)
        return self._injected_status

    def complete(self):
        """
        Return a status object tied to 'done'.
        """
        if self._done_status is None:
            raise RuntimeError("must call kickoff() before complete()")
        return self._done_status

    def collect(self):
        """
        Yield events that reference the data files generated by HPLC.
        the HPLC run using a batch file should always export data into /nsls2/xf16id1/Windows/hplc_export.txt
        """

        # in principle there are lots of things that can be saved
        # for now just keep the chromatograms
        sections = readShimadzuDatafile('/nsls2/xf16id1/Windows/hplc_export.txt', return_all_sections=True)
        
        import numpy as np
        yield {'time': time.time(),
               'seq_num': 1,
               'data': {'foo': np.random.rand(2048, 1)},
               'timestamps': {'foo': time.time()}}

        # TODO Decide whether you want to 'chunk' the dataset into 'events'.
        # Insert a datum per event and yield a partial event document.
        #for i in range(1):
        #    yield {'time': time.time(),
        #           'seq_num': i+1,
        #           'data': {'foo': np.random.rand(2048, 1)},  #datum_id},
        #           'timestamps': {'foo': time.time()}}

    def describe_collect(self):
        return {self.name: {'foo': {'dtype': 'array',
                             'shape': (2048,),
                             'source': 'TO DO'}}}

    def _injected_changed(self, value, old_value, **kwargs):
        """Mark the status object returned by 'kickoff' as finished when
        injected goes from 0 to 1."""
        if self._injected_status is None:
            return
        if (old_value == 0) and (value == 1):
            self.ready.set(0)
            self.hplc_status = HPLCStatus.waiting_done
            self._injected_status._finished()

    def _done_changed(self, value, old_value, **kwargs):
        """Mark the status object returned by 'complete' as finished when
        done goes from 0 to 1."""
        if self._done_status is None:
            return
        if (old_value == 0) and (value == 1):
            self.hplc_status = HPLCStatus.idle
            self._done_status._finished()

    def _bypass_changed(self, value, old_value, **kwargs):
        """Mark the status object returned by 'complete' as finished when
        done goes from 0 to 1."""
        if value == 0:
            return
        print('Bypass used: {}, hplc state: {}'.format(value, self.hplc_status))
        if (value == 1) and self.hplc_status == HPLCStatus.waiting_injected:
            self._injected_changed(1,0)
        elif (value == 2) and self.hplc_status == HPLCStatus.waiting_done:
            self._done_changed(1,0)
        self.bypass.set(0)


class LoudLivePlot(LivePlot):
    def event(self, doc):
        if 'usb4000_region1_luminscence' in doc['data']:
            print(doc['seq_num'])
        super().event(doc)


def hplc_scan(detectors, monitors, *, md=None):
    if md is None:
        md = {}
    md = ChainMap(md,
                  {'plan_name': 'hplc_scan'})

    @fast_shutter_decorator() 
    #@subs_decorator(LiveTable([usb4000.region1.luminescence.name]))
    #@subs_decorator(LoudLivePlot(usb4000.region1.luminescence.name))
    @stage_decorator([hplc] + detectors)
    #@monitor_during_decorator(monitors)
    @run_decorator(md=md)
    def inner():
        print('Beamline Ready... waiting for HPLC Injected Signal')
        yield from kickoff(hplc, wait=True)
        print('Acquiring data...')
        for mo in monitors:
            yield from monitor(mo)
        status = yield from complete(hplc, wait=False)
        while True:
            yield from trigger_and_read(detectors)  # one 'primary' event per loop
            if status.done:
                break
        for mo in monitors:
            yield from unmonitor(mo)
        print('Collecting the data...')
        yield from collect(hplc)

    return (yield from inner())

"""
def collect_hplc(sample_name, exp):#, CV=24, flowrate=0.5)
    change_sample(sample_name)
    sol.select_flow_cell('middle')
    #time = CV/flowrate
    #no_of_cts = time * 60/exp
    set_pil_num_images(1)
    pilatus_ct_time(exp)
    update_metadata()
    RE(hplc_scan(detectors=[pil1M, pilW1, pilW2, em1, em2], monitors=[]))
"""
        
hplc = HPLC('XF:16IDC-ES:Sol{ctrl}HPLC', name='hplc', read_filepath=None, write_filepath=None)
