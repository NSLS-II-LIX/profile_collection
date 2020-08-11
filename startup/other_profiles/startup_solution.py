from py4xs.hdf import h5sol_HT,h5exp
import time,sys,random
#global DET_replace_data_path
#DET_replace_data_path = True

PilatusFilePlugin.froot = data_file_path.gpfs
PilatusCBFHandler.froot = data_file_path.gpfs
froot=data_file_path.gpfs

sol = SolutionScatteringExperimentalModule()

def showd2s(d2, logScale=True, showMask=False, clim=(0.1,14000), showRef=True, cmap=None):
    plt.figure()
    ax = plt.gca()
    pax = Axes2dPlot(ax, d2.data, exp=d2.exp)
    pax.plot(log=logScale)
    if cmap is not None:
        pax.set_color_scale(plt.get_cmap(cmap)) 
    if showMask:
        pax.plot(log=logScale, mask=d2.exp.mask)
    pax.img.set_clim(*clim)
    pax.coordinate_translation="xy2qphi"
    if showRef:
        pax.mark_standard("AgBH", "r:")
    plt.show() 

import pandas
import numpy as np

min_load_volume = 20

def gettimestamp():
    ts = time.localtime()
    return f"{ts.tm_year}-{ts.tm_mon:02d}-{ts.tm_mday:02d}_{ts.tm_hour:02d}{ts.tm_min:02d}"

def pack_ref_h5(run_id):
    uids = list_scans(run_id=run_id, holderName="reference")
    send_to_packing_queue('|'.join(uids), "multi",froot=data_file_path.gpfs)    
    # consider adding the ref intensity to the h5 file, need to know when the file is ready
    
def plot_ref_h5():
    pass
    
def collect_std():
    holderName = "std"
    RE.md['holderName'] = holderName
    pil.use_sub_directory(holderName)
    pil.set_trigger_mode(PilatusTriggerMode.soft)
    pil.set_num_images(1)
    pil.exp_time(0.5)
    ts = gettimestamp()

    r_range = 2.
    sol.sample_y.move(sol.flowcell_pos['std'] + r_range*(random.random()-0.5))
    
    change_sample(f"AgBH-{ts}")
    RE(ct([pil,em1,em2], num=1))
    
    pil.use_sub_directory()
    del RE.md['holderName']

    # now pack h5 file and recalibrate
    pack_h5([last_scan_uid], fn="std.h5")
    dexp = h5exp("exp.h5")
    dexp.recalibrate("std.h5")


def collect_reference():
    nd_list = ['upstream','downstream']
    holderName='reference'
    RE.md['holderName'] = holderName
    pil.use_sub_directory(holderName)
    ts = gettimestamp()   
    pil.set_trigger_mode(PilatusTriggerMode.ext_multi)
    pil.set_num_images(5)
    pil.exp_time(1)
    
    for nd in nd_list:
        fcell = sol.flowcell_nd[nd]
        sol.select_flow_cell(fcell)
        sol.wash_needle(nd, option="wash only")
        
        for ref in ['water','blank']:
            #em1.averaging_time.put(0.25)
            #em2.averaging_time.put(0.25)
            #em1.acquire.put(1)
            #em2.acquire.put(1)
            #sd.monitors = [em1.sum_all.mean_value, em2.sum_all.mean_value]
            sname = f"{fcell}_{ref}_{ts}"
            if ref=='blank':
                sol.wash_needle(nd, option="dry only")
            change_sample(sname)
            RE(ct([pil,em1,em2], num=5))
            #sd.monitors = []
    pil.use_sub_directory()
    del RE.md['holderName']    

ref_beam_intensity = {"em1": 4200000, "em2": 160000}
beam_intensity_history = {"em1": [], "em2": [], "timestamp": []}    
    
def log_ref_intensity(thresh=0.05, update=False):    
    RE(ct([em1,em2], num=10)) 
    
    h = db[-1]
    sn='em1_sum_all_mean_value_monitor' if 'em1_sum_all_mean_value_monitor' in h.stream_names else 'primary' 
    Io = np.average(h.table(stream_name=sn)['em1_sum_all_mean_value'])        
    sn='em2_sum_all_mean_value_monitor' if 'em2_sum_all_mean_value_monitor' in h.stream_names else 'primary' 
    It = np.average(h.table(stream_name=sn)['em2_sum_all_mean_value'])        

    if update:
        ref_beam_intensity['em1'] = Io
        ref_beam_intensity['em2'] = It
    if np.fabs(ref_beam_intensity['em1']-It)/It>thresh:
        # do a scan if the intensity got higher as well
        return False
    beam_intensity_history['em1'].append(Io)
    beam_intensity_history['em2'].append(It)
    beam_intensity_history['timestamp'].append(time.time())
    return True
    
def check_beam(It_thresh=10000):
    RE.md['tag']='alignment_check'

    if ref_beam_intensity['em1'] is not None:
        if log_ref_intensity():
            del RE.md['tag']
            return 
    
    mono.y.settle_time = 2
    RE(dscan([em1,em2], mono.y, -0.3, 0.3, 40))
    mono.y.settle_time = 0

    d = db[-1].table()
    x = d['dcm_y']
    y = d['em2_current1_mean_value']
    if np.max(y)<It_thresh:
        raise Exception("not seeing enough intensity on em2, a more thorough check is needed !")
    
    x0 = np.average(x[y>(1.-thresh)*np.max(y)])
    RE(mv(mono.y, x0))
    log_ref_intensity(update=True)
    
    del RE.md['tag']

beam_current = EpicsSignal('SR:OPS-BI{DCCT:1}I:Real-I')
bpm_current = EpicsSignal('XF:16IDB-CT{Best}:BPM0:Int')
PShutter = EpicsSignal('XF:16IDB-PPS{PSh}Enbl-Sts')
previous_beam_on_status = True

def verify_beam_on(beam_cur_thresh=300, bpm_cur_thresh=1.e-7):
    global previous_beam_on_status
    # returns True is the beam intensity is normal
    # for now just check ring current
    beam_on_status = (beam_current.get()>=beam_cur_thresh)
    if beam_on_status and not previous_beam_on_status:
        # if the ring current recovers from below the threshold, check alignment
        log_ref_intensity()
    previous_beam_on_status = beam_on_status
    # in case someone forgot to open the shutter
    if beam_on_status and previous_beam_on_status:
        while np.average(bpm_current.get())<bpm_cur_thresh:
            if not PShutter.get():
                input("open the shutter and hit any key to continue ...")
            else:
                print("BPM counts too low, attempting to re-align the beam ...")
                check_beam()
    return beam_on_status
    

def parseSpreadsheet(infilename, sheet_name=0, strFields=[]):
    """ dropna removes empty rows
    """
    converter = {col: str for col in strFields} 
    DataFrame = pandas.read_excel(infilename, sheet_name=sheet_name, converters=converter)
    DataFrame.dropna(axis=0, how='all', inplace=True)
    return DataFrame.to_dict()

def get_samples(spreadSheet, holderName, sheet_name=0,
                check_for_duplicate=False, configName=None,
                requiredFields=['sampleName', 'holderName', 'position'],
                optionalFields=['volume', 'exposure', 'bufferName'],
                autofillFields=['holderName', 'volume', 'exposure'],
                strFields=['sampleName', 'bufferName', 'holderName'], 
                numFields=['volume', 'position', 'exposure']):
    d = parseSpreadsheet(spreadSheet, sheet_name, strFields)
    tf = set(requiredFields) - set(d.keys())
    if len(tf)>0:
        raise Exception(f"missing fields in spreadsheet: {list(tf)}")
    autofillSpreadsheet(d, fields=autofillFields)
    allFields = list(set(requiredFields+optionalFields).intersection(d.keys()))
    for f in list(set(allFields).intersection(strFields)):
        for e in d[f].values():
            if not isinstance(e, str):
                if not np.isnan(e):
                    raise Exception(f"non-string value in {f}: {e}")
    for f in list(set(allFields).intersection(numFields)):
        for e in d[f].values():
            if not (isinstance(e, int) or isinstance(e, float)):
                raise Exception(f"non-numerical value in {f}: {e}")
            if e<=0 or np.isnan(e):
                raise Exception(f"invalid value in {f}: {e}, possitive value required.")
    if 'volume' in allFields:
        if np.min(list(d['volume'].values()))<min_load_volume:
            raise Exception(f"load volume must be greater than {min_load_volume} ul!")

    # check for duplicate sample name
    sl = list(d['sampleName'].values())
    for ss in sl:
        if not check_sample_name(ss, check_for_duplicate=False):
            raise Exception(f"invalid sample name: {ss}")
        if sl.count(ss)>1 and str(ss)!='nan':
            idx = list(d['holderName'])
            hl = [d['holderName'][idx[i]] for i in range(len(d['holderName'])) if d['sampleName'][idx[i]]==ss]
            for hh in hl:
                if hl.count(hh)>1:
                    raise Exception(f'duplicate sample name: {ss} in holder {hh}')
    # check for duplicate sample position within a holder
    if holderName is None:
        hlist = np.unique(list(d['holderName'].values()))
    else:
        hlist = [holderName]
    idx = list(d['holderName'])
    for hn in hlist:
        plist = [d['position'][idx[i]] for i in range(len(d['holderName'])) if d['holderName'][idx[i]]==hn]
        for pv in plist:
            if plist.count(pv)>1:
                raise Exception(f"duplicate sample position: {pv}")
                
    if holderName is None:  # validating only
        # the correct behavior should be the following:
        # 1. for a holder scheduled to be measured (configName given), there should not be an existing directory
        holders = list(get_holders(spreadSheet, configName).values())
        for hn in holders:
            if not check_sample_name(hn, check_for_duplicate=True, check_dir=True):
                raise Exception(f"change holder name: {hn}, already on disk." )
        # 2. for all holders in the spreadsheet, there should not be duplicate names, however, since we are
        #       auto_filling the holderName field, same holder name can be allowed as long as there are no
        #       duplicate sample names. Therefore this is the same as checking for duplicate sample name,
        #       which is already done above
        return

    # columns in the spreadsheet are dictionarys, not arrays
    idx = list(d['holderName'])  
    hdict = {d['position'][idx[i]]:idx[i] 
             for i in range(len(d['holderName'])) if d['holderName'][idx[i]]==holderName}
        
    samples = {}
    allFields.remove("sampleName")
    allFields.remove("holderName")
    for i in sorted(hdict.keys()):
        sample = {}
        sampleName = d['sampleName'][hdict[i]]
        holderName = d['holderName'][hdict[i]]
        for f in allFields:
            sample[f] = d[f][hdict[i]]
        if "bufferName" in sample.keys():
            if str(sample['bufferName'])=='nan':
                del sample['bufferName']
        samples[sampleName] = sample
            
    return samples


def autofillSpreadsheet(d, fields=['holderName', 'volume']):
    """ if the filed in one of the autofill_fileds is empty, duplicate the value from the previous row
    """
    col_names = list(d.keys())
    n_rows = len(d[col_names[0]])
    if n_rows<=1:
        return
    
    for ff in fields:
        if ff not in d.keys():
            #print(f"invalid column name: {ff}")
            continue
        idx = list(d[ff].keys())
        for i in range(n_rows-1):
            if str(d[ff][idx[i+1]])=='nan':
                d[ff][idx[i+1]] = d[ff][idx[i]] 
                
                
def get_holders(spreadSheet, configName):
    holders = {}
    d = parseSpreadsheet(spreadSheet, 'Configurations')
    autofillSpreadsheet(d, fields=["Configuration"])
    idx = list(d['Configuration'].keys())
    for i in range(len(idx)):
        if d['Configuration'][idx[i]]==configName:
            holders[d['holderPosition'][idx[i]]] = d['holderName'][idx[i]]

    return holders
                
                
def measure_holder(spreadSheet, holderName, sheet_name='Holders', exp_time=1, repeats=5, vol=45, 
                   returnSample=True, concurrentOp=False, checkSampleSequence=False, 
                   em2_thresh=30000, check_bm_period=900):
    #print('collecting reference')
    #collect_reference()
    #pack_ref_h5(run_id)
    samples = get_samples(spreadSheet, holderName, sheet_name='Holders')

    uids = []
    if concurrentOp and checkSampleSequence:
        # count on the user to list the samples in the right sequence, i.e. alternating 
        # even and odd tube positions, so that concurrent op makes sense
        spos = np.asarray([samples[k]['position'] for k in samples.keys()])
        if ((spos[1:]-spos[:-1])%2 == 0).any():
            raise Exception('the sample sequence is not optimized for concurrent ops.')
    
    pil.use_sub_directory(holderName)
    RE.md['holderName'] = holderName 

    for k,s in samples.items():
        check_pause()
        if 'exposure' in s.keys():
            exp_time = s['exposure']
        if 'volume' in s.keys():
            vol = s['volume']
        while True:
            # make sure the beam is on, wait if not
            while not verify_beam_on():
                time.sleep(check_bm_period)

            sol.measure(s['position'], vol=vol, exp=exp_time, repeats=repeats, sample_name=k, 
                        returnSample=returnSample, concurrentOp=concurrentOp)
            
            # check beam again, in case that the beam dropped out during the measurement
            while True: 
                if verify_beam_on():
                    break
                # wash the needle first in case we have to wait for the beam to recover
                sol.wash_needle(verify_needle_for_tube(s['position'], None))   
                time.sleep(check_bm_period)
            # check whether the beam was on during data collection; if not, repeat the previous sample
            bim = db[-1].table(stream_name='em2_sum_all_mean_value_monitor')['em2_sum_all_mean_value'] 
            if np.average(bim[-10:])>em2_thresh:  
                break
                # otherwise while loop repeats, the sample is measured again
            
        uids.append(db[-1].start['uid'])
        print(k,":",s)
        
    del RE.md['holderName']
    pil.use_sub_directory()
    HT_pack_h5(samples=samples, uids=uids)
        
    for nd in sol.needle_dirty_flag.keys():
        if sol.needle_dirty_flag[nd]:
            sol.wash_needle(nd)
    
    return uids,samples


def validate_sample_spreadSheet_HT(spreadSheet, sheet_name=0, holderName=None, configName=None):
    """ the spreadsheet should have a "Holders" tab and a "Configurations" tab
        the "holders" tab describes the samples in each PCR tube holder
        the "configurations" tab describes how the tube holders are loaded into the storage box
        ideally the holder or configuration name should not be a number due to parsing problems 
        if neither holderName or configName is given, check all holders
    """
    # force check spreadsheet, mainly for sample names 
    samples = get_samples(spreadSheet, holderName=holderName, configName=configName, sheet_name=sheet_name, check_for_duplicate=True)

    
def check_pause():
    if sol.ctrl.pause_request.get():
        sol.ctrl.pause_request.put(2)
        rbt.park()
        print("data collection paused ... ", end="")
        t0 = time.time()
    else:
        return
    
    
    while sol.ctrl.pause_request.get()>0:
        print(f"data collection paused ... {int(time.time()-t0)}  \r", end="")
        sys.stdout.flush()
        time.sleep(1)
    rbt.goHome()
            
    
def auto_measure_samples(spreadSheet, configName, exp_time=1, repeats=5, vol=45, sim_only=False,
                        returnSample=True, concurrentOp=False, checkSampleSequence=False):
    """ measure all sample holders defined in a given configuration in the spreadsheet
    """
    validate_sample_spreadSheet_HT(spreadSheet, sheet_name="Holders", configName=configName)

    if data_path is None:
        raise exception("login first !")
    if sol.HolderPresent.get():
        raise Exception("A sample holder is still in the sample handler !")

    holders = get_holders(spreadSheet, configName)
    rbt.goHome()

    for p in list(holders.keys()):
        sol.sample_y.home('forward')
        sol.select_flow_cell('bottom')
        print('mounting tray from position', p)
        rbt.loadTray(p)

        sol.select_tube_pos('park')

        rbt.mount()
        print('mounted tray =', p)
        holderName = holders[p]

        if sim_only:
            sol.select_tube_pos(1)
            countdown("simulating data collection ", 60)
        else:
            uids,samples = measure_holder(spreadSheet, holderName,
                                          exp_time=exp_time, repeats=repeats, vol=vol,
                                          returnSample=returnSample, concurrentOp=concurrentOp,
                                          checkSampleSequence=checkSampleSequence)

        sol.select_tube_pos('park')

        try:  # this sometimes craps out, but never twice in a row
            rbt.unmount()
        except:
            rbt.unmount()
        #rbt.unloadTray(d['holderPosition'][i])
        rbt.unloadTray(p)
        
    rbt.park()


def HT_pack_h5(spreadSheet=None, holderName=None, froot=data_file_path.gpfs, 
               run_id=None, samples=None, uids=None, **kwargs):
    """ this is useful for packing h5 after the experiment
        it will not perform buffer subtraction
    """
    if samples is None:
        samples = get_samples(spreadSheet, holderName, sheet_name="Holders")
    if uids is None:
        uids = list_scans(run_id=run_id, holderName=holderName, **kwargs)

    sb_dict = {}
    for s in samples.keys():
        if 'bufferName' in samples[s].keys():
            sb_dict[s] = [samples[s]['bufferName']]
    uids.append(json.dumps(sb_dict))
    send_to_packing_queue('|'.join(uids), "sol", froot)
    
            
def createShimadzuBatchFile(spreadsheet_fn, batchID, sheet_name='Samples', 
                            check_sname=True, shutdown=False,
                            strFields=['Method File', 'Sample Name'], numFields=['Inj. Volume']):
    """ spreadsheet requiredColumns: sampleName, columnID, flowrate, runTime, collectionTime
        columnID: should be from a dropdown list to avoid problems
        ??collectionTime: the part of the HPLC run when data are actually collected
    """
    template_batch_file = "/nsls2/xf16id1/Windows/HPLC/template/batch_template.txt"
    template_method_file = "/nsls2/xf16id1/Windows/HPLC/template/method_template.lcm"
    sections = readShimadzuDatafile(template_batch_file, return_all_sections=True)
    dd = parseSpreadsheet(spreadsheet_fn, sheet_name=sheet_name, strFields=['batchID', 'Tray Name'])
    autofillSpreadsheet(dd, fields=['batchID', 'Tray Name'])
    ridx = [i for i in dd['batchID'].keys() if dd['batchID'][i]==batchID] 
    nrows = len(ridx)

    for i in ridx:
        for f in strFields:
            if not isinstance(dd[f][i], str):
                raise Exception(f"not a string for {f}: {dd[f][i]}")
        for f in numFields:
            if not (isinstance(dd[f][i], int) or isinstance(dd[f][i], float)) :
                raise Exception(f"not a nemeric value for {f}: {dd[f][i]}")
    
    if proposal_id is None or run_id is None:
        print("need to login first ...")
        login()

    default_HPLC_path = '/nsls2/xf16id1/Windows/HPLC/'    
    default_data_path = '/nsls2/xf16id1/Windows/HPLC/%s/%s/' % (proposal_id,run_id)
    default_hplc_export_file = 'File\tZ:\\hplc_export.txt'
    default_win_HPLC_dir = 'Z:\\HPLC\\'
    default_win_data_path = default_win_HPLC_dir+proposal_id+'\\'+run_id+'\\'
    # make directory, makedirs() is defined in 02-utils.py
    makedirs(default_data_path)

    # some contents of the sample info need to be generated automatically
    dd['Sample ID'] = {}
    dd['Data File'] = {}
    samples = {}
    for i in ridx:
        sn = dd['Sample Name'][i]
        acq_time = float(dd['Run Time'][i])
        cid = int(dd['Column#'][i])
        cl_type = dd['Column Type'][i]
        inj_vol = float(dd['Inj. Volume'][i])
        #flowrates = [float(dd['Flow Rate A'][i]), float(dd['Flow Rate B'][i])]
        flowrate = float(dd['Flow Rate B'][i])

        dd['Sample ID'][i] = sn
        dd['Data File'][i] = default_win_data_path+sn+'.lcd'
        samples[sn] = {"acq time": acq_time, 
                       "Column ID": cid, 
                       #"flowrates": flowrates, 
                       "md": {"Column Type": cl_type,
                              "Injection Volumn (ul)": inj_vol,
                              "Flow Rate (ml_min)": flowrate}
                      }
    
    # make sure there are no repeating sample names
    slist = list(samples.keys())
    for sn in slist:
        if slist.count(sn)>1:
            raise Exception('duplicate sample name in the spreadsheet: %s' % sn)
        if not check_sample_name(sn, check_for_duplicate=check_sname, check_dir=True):
            # assuming that the data will be written into a directory named after the sample
            raise Exception()
    
    sections['[ASCII Convert]'][1] = default_hplc_export_file
    sections['[ASCII Convert]'][2] = 'Auto-Increment\t0'
    # create the batch table
    batch_table = []
    batch_table.append('# of Row\t%d' % nrows)
    batch_table.append(sections['[Batch Table]'][1])
    batch_para_name = sections['[Batch Table]'][1].split('\t')
    batch_para_value = sections['[Batch Table]'][2].split('\t')

    default_batch_values = {'Report Format File': 'VG_Report_Format.lsr'
                           }
    
    # copy all valid columns from the spreadsheet to the batch file
    # use default values (from the template file) for all missing columns
    for i in ridx:
        entry = []
        for j in range(len(batch_para_name)):
            if batch_para_name[j] in dd.keys():
                entry.append(str(dd[batch_para_name[j]][i]))
            elif batch_para_name[j] in default_batch_values.keys():
                entry.append(str(default_batch_values[batch_para_name[j]]))
            else:
                entry.append(str(batch_para_value[j]))
        batch_table.append('\t'.join(entry))

    sections['[Batch Table]'] = batch_table
    
    if shutdown:
        sections['[Shutdown]'] = ['Mode\t1', 'Use Method File\t1',
                                  'File\tC:\\LabSolutions\\Data\\Project1\\JB_PUMP_SHUTOFF.lcm',
                                  'Cool Down Time\t0', 'ELSD Valve\t0', 'MS Settings\t1031', 'MS Settings2\t0']
    
    batch_file_name = sheet_name+'_batch.txt'
    writeShimadzuDatafile(default_HPLC_path+batch_file_name, sections)
    
    return batch_file_name,default_win_data_path,samples


    
def collect_hplc(sample_name, exp, nframes):
    change_sample(sample_name)
    pil.use_sub_directory(sample_name)
    sol.select_flow_cell('middle')
    pil.set_trigger_mode(PilatusTriggerMode.ext_multi)
    pil.set_num_images(nframes)
    pil.exp_time(exp)
    update_metadata()
   
    em1.averaging_time.put(0.25)
    em2.averaging_time.put(0.25)
    em1.acquire.put(1)
    em2.acquire.put(1)
    sd.monitors = [em1.sum_all.mean_value, em2.sum_all.mean_value]
   
    #hplc.ready.set(1)
    while hplc.injected.get()==0:
        if hplc.bypass.get()==1:
            hplc.bypass.put(0)
            break
        sleep(0.2)

    #hplc.ready.set(0)
    RE(ct([pil], num=nframes))
    sd.monitors = []
    pil.use_sub_directory()
    change_sample()
     

def run_hplc_from_spreadsheet(spreadsheet_fn, batchID, sheet_name='Samples', exp=1, shutdown=False):
    batch_fn,winDataPath,samples = createShimadzuBatchFile(spreadsheet_fn, batchID=batchID,
                                                           sheet_name=sheet_name, 
                                                           check_sname=True,
                                                           shutdown=shutdown)
    print("HPLC batch file has been created in %s: %s" % (winDataPath,batch_fn))
    input("please start batch data collection from the Shimadzu software, then hit enter:")
    for sn in samples.keys():
        RE.md['HPLC'] = samples[sn]['md']
        print(f"collecting data for {sn} ...")
        # for hardware multiple trigger, the interval between triggers is slightly longer
        #    than exp. but this extra time seems to fluctuates. it might be safe not to include
        #    it in the caulcation of nframes
        collect_hplc(sn, exp=exp, nframes=int(samples[sn]["acq time"]*60/exp))   
        uid=db[-1].start['uid']
        send_to_packing_queue(uid, "HPLC", froot=data_file_path.gpfs)
        del RE.md['HPLC']
    pil.use_sub_directory()    
    print('batch collection collected for %s from %s' % (sheet_name,spreadsheet_fn))

    ## copy the exported data file for backup
    # check time stamp to make sure it has been updated recently (e.g. within a minute)?? 
    wdir = "/nsls2/xf16id1/Windows/"
    os.system(f"cp {wdir}hplc_export.txt {wdir}HPLC/{proposal_id}/{run_id}/export-{batchID}.txt")

    
sol.default_wash_repeats=2
sol.default_dry_time=20
sol.vol_sample_headroom = 10 

hplc.ready.set(0)
