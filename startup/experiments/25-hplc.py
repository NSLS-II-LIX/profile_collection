print(f"Loading {__file__}...")
import socket
import numpy as np
from time import sleep
import signal
import itertools
import pathlib, subprocess
windows_ip = '10.66.123.226'

TCP_IP = '10.66.122.159'  ##moxa on HPLC cart.  Port 1 is valve, Port 2 is regen pump, Port 3 will contain all VICI valves
Pump_TCP_PORT = 4002
VICI_TCP_PORT = 4003
socket.setdefaulttimeout(10)
timeout=socket.getdefaulttimeout()
print(timeout)
class pump_SSI:
    def __init__(self):
        self.sock=socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((TCP_IP, Pump_TCP_PORT))
        self.get_status()
        self.get_status()
    
    def send_cmd(self,cmd):
        self.sock.sendall(cmd.encode())
        data = self.sock.recv(1024)
        ret=data.decode("UTF-8")
        print(data.decode("UTF-8"))
        print(ret)
        return ret
    
    def get_flowrate(self, print_flow=True):
        fret=[]
        data=self.send_cmd("CS")
        a=data.split(",")
        print(a)
        fret.append(a[1])
        ret = float(fret[0])
        return ret
    
    def get_status(self, cmd="CS"):
        """
        Format of output"
        OK, flowrate, Upper pressure limit, lower pressure limit, pressure units, Run/Stop status, a zero (seems to be flowset point?
        Run/Stop Status 0=pump stopped, 1 = running
        """
        ret=self.send_cmd(cmd=cmd)
        print("Pump SSI status:" f'{ret[0]}')
    
    def start_pump(self, cmd='RU'):
        self.send_cmd(cmd=cmd)
        #print(ret)
    
    def stop_pump(self, cmd="ST"):
        self.send_cmd(cmd=cmd)
        #print(ret)

    def split_decimal(self,flowrate):
        # Split the number into integer and decimal parts since the pump reads FI00000
        integer_part = int(flowrate)
        decimal_part = round(flowrate - integer_part, 3)

        # Convert the integer part to a string and pad with zeros
        integer_str = str(integer_part)
        if len(integer_str) < 2:
            integer_str=integer_str.zfill(2)
            print(integer_str)

        # Convert the decimal part to a string with 3 decimal places
        decimal_str = "{:.3f}".format(decimal_part)[2:]  # remove "0." prefix

        # Pad the decimal string with leading zeros if necessary
        if len(decimal_str) < 3:
            decimal_str = decimal_str.ljust(3, '0')
        elif len(decimal_str) > 5:
            decimal_str = decimal_str[:3]

        # Return the integer and decimal strings
        return integer_str, decimal_str
    
    def set_flowrate(self,flowrate=0.3):
        if int(flowrate) > 12:
            raise Exception("Max flowrate is 12mL/min!")
        else:
            integer_str,decimal_str=self.split_decimal(flowrate)
        self.send_cmd(cmd="FI"+ integer_str + decimal_str)
        
    def read_pressure(self):
        #read pressure before making changes and monitor if necessary.Should not read values in a regular interval because of message clashing
        press_units=self.send_cmd("PU")
        current_press=self.send_cmd("PR")
        return press_units, current_press
    
    def set_upper_pressure_limit(self, upper_pressure=750):
        ##max pressure in psi, this is column dependent. 725psi for the superdex columns
        self.send_cmd("UP"+ str(upper_pressure))
        ret=self.get_status()
        print(ret)
    
    def set_lower_pressure_limit(self, lower_pressure=25):
        ##max pressure in psi, this is column dependent. 725psi for the superdex columns
        self.send_cmd("LP"+ str(lower_pressure))
        ret=self.get_status()
        print(ret)
        
        
##class to control methods on regeneration pump
class regen_ctrl(pump_SSI):
    def __init__(self, column_type):
        self.column_type=column_type
        super().__init__(self)
    def setup_method(flowrate=0.1, max_pressure=700, time=None):
        ret=regen_ctrl.get_status()
        if ret[0] == "OK":
            regen_ctrl.set_flowrate(flowrate = flowrate)
            regen_ctrl.set_upper_pressure_limit(max_pressure=max_pressure)
            ret=regen_ctrl.get_status
            print(ret)
        else:
            raise Exception("Pump Status not OK")
        flowrate = flowrate
        
TRP=pump_SSI()




###Commands for 10-port valve.  Setup as regeneration pump and used for co-flow (in-progress).

class VICI_valves:
    def __init__(self):
        self.sock=socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((TCP_IP, VICI_TCP_PORT))
        #self.get_status()
        #self.get_status()
        
    def send_valve_cmd(self, cmd, ID, get_ret=False):
        cmd=f"{ID}{cmd}\r"
        print(cmd)
        self.sock.sendall(cmd.encode())
        print(f"Command {cmd} has been sent to valve {ID}")
        #time.sleep(0.2)
        if cmd==f'{ID}GOA\r':
            print("changed, no return output")
        elif cmd==f'{ID}GOB\r':
            print("changed, no return output")
        elif cmd==f'{ID}GO\r':
            print("GO issued command, no return output")
        if get_ret:
            ret=self.sock.recv(1024)
            ascii_ret=ret.decode("ascii")
            print(ascii_ret)
            return ret, ascii_ret
            #self.sock.close()
    
    def check_valve_pos(self, ID):
        cmd = f"{ID}CP\r"
        self.sock.sendall(cmd.encode())
        time.sleep(0.1)
        print(f"Getting {ID} Valve status")
        ret = self.sock.recv(1024)
        ascii_ret = ret.decode("ascii")
        print(ascii_ret)
        print(ascii_ret[-3])
        return ascii_ret
        
    def switch_10port_valve(self, pos="A", ID=1, get_ret=False):
        cur_pos=self.check_valve_pos(ID=ID)  ## format is "Postion is A' \r"
        if cur_pos[-3] == pos:
            print(f"10-port Valve already at {pos}!")
        
        elif cur_pos[-3] != pos:
            if pos=="A":
                self.send_valve_cmd("GOA", ID=ID)
            elif pos=="B":
                self.send_valve_cmd("GOB", ID=ID)
        else:
            raise Exception(f"{pos} is not a valid command to change 10-port valve! Use 'A' or 'B'.")
    
VV = VICI_valves()   


       
 ####Running HPLC 


def CreateAgilentSeqFile(spreadsheet_fn, batchID, sheet_name='Samples'):
    
    """
    Creates the agilent sequence file from the spreadsheet. User input is batchID, sample_name and method for hplc. The other columns are necessary for generating the proper formatted sequence file
    """
    strFields=["Vial", "Sample Name", "Sample Type", "Acq. method", "Proc. method", "Data file", "Buffer", "Valve Position"]
    numFields=["Volume"]
    dd=parseSpreadsheet(spreadsheet_fn, sheet_name=sheet_name, return_dataframe=False)
    print(f"this is {dd}")
    autofillSpreadsheet(dd, fields=["batchID"])
    print(dd['batchID'].keys())
    print(dd['batchID'].values())
    print(dd['Valve Position'].values())
    
    if proposal_id is None or run_id is None:
        print("need to login first ...")
        login()
    
    ridx=[i for i in dd['batchID'].keys() if dd['batchID'][i]==batchID]
    print(f"{ridx} this is ridx")

    
    samples = {}
    dfile = f"{current_cycle}/{proposal_id}/{run_id}/<S>" 
    dd["Data File"] = {}
    dd["Sample Type"] = {}
    valve_position = {}
        
    for i in ridx:
        for f in numFields:
            if not (isinstance(dd[f][i], int or isintance(dd[f][i], float))):
                raise Exception(f"not a numeric value for {f}: {dd[f][i].values()}, replace with number")
        valve_position[i] = dd["Valve Position"][i]
        print(valve_position)
        sn = dd['Sample Name'][i]
        samples[sn] = {"acq time": dd['Run Time'][i], 
                       "valve_position":valve_position[i],
                       "md": {"Column type": dd['Column type'][i],
                              "Injection Volume (ul)": dd['Volume'][i],
                              "Flow Rate (ml_min)": dd['Flow Rate'][i],
                              "Sample buffer":dd['Buffer'][i],
                              "Valve Position":valve_position[i]}
                      }
        dd["Data File"][i] = dfile
        dd["Valve Position"][i]
        dd["Sample Type"][i] = "Sample"
    sequence_path="/nsls2/data4/lix/legacy/HPLC/Agilent/"
    df=pd.DataFrame.from_dict(dd, orient='columns')
    df[df['batchID']==batchID].to_csv(f"{sequence_path}sequence_table.csv", index=False, encoding="ASCII",
                    columns=["Vial", "Sample Name", "Sample Type", "Volume", "Inj/Vial", "Acq. method", "Proc. method", "Data File" ])
    source_file = f"{sequence_path}"+'sequence_table.csv'
    destination_loc = "xf16id@10.66.123.226:C:/CDSProjects/HPLC/"
    try:
            ssh_key = str(pathlib.Path.home())+"/.ssh/id_rsa.pub"
            if not os.path.isfile(ssh_key):
                raise Exception(f"{ssh_key} does not exist!")
            cmd = ["scp", "/nsls2/data4/lix/legacy/HPLC/Agilent/sequence_table.csv", destination_loc] ##hardcoded path for sequence file
            #print(cmd)
            subprocess.run(cmd)
            print("Sequence_table sucessfully sent")
    except Exception as e:
        print(f"SCP transfer has failed for {cmd}!")

    return samples, valve_position  


        
def run_hplc_from_spreadsheet(spreadsheet_fn, batchID, sheet_name='Samples', exp=1, shutdown=False):
    batch_fn = '/nsls2/data/lix/legacy/HPLC/Agilent/sequence_table.csv'
    samples, valve_position = CreateAgilentSeqFile(spreadsheet_fn, batchID, sheet_name=sheet_name)
    print(f"HPLC sequence file has been created in: {batch_fn}")
    print("Make sure you have selected the correct valve position for column type!")
    input("Please start Sequence in Agilent software by importing sequence_table.csv (under sequence tab), click run, then come back to this machine and then hit enter:")
    for sn in samples.keys():
        VV.switch_10port_valve(pos=samples[sn]["md"]["Valve Position"])
        print(f"Switching valve to position {samples[sn]['md']['Valve Position']}!")
        caput('XF:16IDC-ES:{HPLC}SampleName', sn)
        print(f"collecting data for {sn} ...")

            #print(f"Switching to valve position {pos}!")
            #switch_10port_valve(pos=pos)
        # for hardware multiple trigger, the interval between triggers is slightly longer
        #    than exp. but this extra time seems to fluctuates. it might be safe not to include
        #    it in the caulcation of nframes
        
        collect_hplc(sn, exp=exp, nframes=int(samples[sn]["acq time"]*60/exp), md={'HPLC': samples[sn]['md']})   
        uid=db[-1].start['uid']
        send_to_packing_queue(uid, "HPLC")
    pil.use_sub_directory()
    move_hplc_files(current_sample=current_sample)
#    h5_attach_hplc(fn_h5=None)
    
    print('Sequence collection finished for %s from %s' % (batchID,spreadsheet_fn))


def scp_transfer(cmd):
        """To handle copying files from lustre to machine running Agilent software and vice versa"""
        try:
            ssh_key = str(pathlib.Path.home())+"/.ssh/id_rsa.pub"
            if not os.path.isfile(ssh_key):
                raise Exception(f"{ssh_key} does not exist!")
            #cmd = cmd
            result = subprocess.run(cmd, capture_output=True, text=True)
            print(result)
            time.sleep(1)
            #self.setParam('TRANSFER', 0)  # Reset trigger after successful transfer
            if result.returncode == 0:
                print("Transfer successful!")
            else:
                raise RuntimeError("Transfer not successful", result.stderr)
            return result
        except Exception as e:
            print(f"SCP transfer has failed for {cmd}!")
 
def move_hplc_files(proposal_id=proposal_id, run_id=run_id,current_cycle=current_cycle,csv=True, **kwargs):
        UV_file_prefix = str(f"{run_id}")
        remote_sample_dir = kwargs.get('current_sample')
        remote_sample_adf = "SiSa_"+f"{current_cycle}-{proposal_id}-{run_id}-"+kwargs.get('current_sample')+'.ADF'
        remote_sample_csv = f"{current_cycle}-{proposal_id}-{run_id}-"+kwargs.get('current_sample')+'.dx_DAD1E.CSV'
        UV_data = str(UV_file_prefix + "-" +remote_sample_csv)
        print(UV_data)
        remote_dir='C:/CDSProjects/HPLC/'
        remote_path = os.path.join(remote_dir, remote_sample_dir, remote_sample_adf)
        remote_path_csv = os.path.join(remote_dir, remote_sample_dir, remote_sample_csv)
        cmd = ["scp", f"xf16id@{windows_ip}:{remote_path}", f"/nsls2/data/lix/legacy/{current_cycle}/{proposal_id}/{run_id}"]
        print(f"Waiting to transfer {remote_sample_adf}....")
        result=scp_transfer(cmd)
        print(result)
        
        if csv==True:
            cmd = ["scp", f"xf16id@{windows_ip}:{remote_path_csv}", f"/nsls2/data/lix/legacy/{current_cycle}/{proposal_id}/{run_id}"]
            print(f"fetching CSV files from {remote_path_csv}")
            result=scp_transfer(cmd)
            print(result)
            
def get_UV_data(sample_name): #proxies=proxies):
    #f=requests.get(f'http://xf16id-ws4:8000/{current_cycle}-{proposal_id}-{run_id}-{sample_name}/{current_cycle}-{proposal_id}-{run_id}-{sample_name}.dx_DAD1E.CSV', proxies=proxies)
    sample_name = f"{current_cycle}-{proposal_id}-{run_id}-{sample_name}.dx_DAD1E.CSV"
    df = pd.read_csv(sample_name)
    k=df.to_numpy(dtype=float)
    #fn_h5=f"{current_sample} +.h5"
    #data=f.text
    #hdstr=dict(f.headers)
    #k=np.genfromtxt(StringIO(data), delimiter=',', dtype="float")
    
    #k=str(k).encode('ASCII')
    #df_uv = pd.read_csv(StringIO(data), sep=',', engine='python', header=None, names=['time','mAU'])
    
    
    return k #df_uv


def h5_attach_hplc(fn, fn_h5=None, grp_name=None):
    """ the hdf5 is assumed to contain a structure like this:
        LIX_104
        == hplc
        ==== data
        == primary (em, scattering patterns, ...)
        
        attach the HPLC data to the specified group
        if the group name is not give, attach to the first group in the h5 file
    """
    if fn_h5 is None:
        fn_h5 = current_sample+".h5"
        print(fn_h5)
    f = h5py.File(fn, "r+")
    if grp_name == None:
        grp_name = list(f.keys())[0]
    sample_name=list(f.keys())[0]
    k=get_UV_data(sample_name)
    # sample_name is in the file name after proposal-saf leaving out check until we verify sample name can be extracted from http server
    #and verified with sample name from HDF5 file generated.  Point is to compare what is read from server to hdf5 file already packing to make sure group name is the same.

    
    # this group is created by suitcase if using flyer-based hplc_scan
    # otherwise it has to be created first
    # it is also possible that there was a previous attempt to populate the data

    if 'hplc' in f[f"{grp_name}"].keys():
        grp = f["%s/hplc/data" % grp_name]
    else:
        grp = f.create_group(f"{grp_name}/hplc/data")
        
    key_list=list(grp.keys())
    for g in grp:
        if g in key_list:
            print("warning: %s already exists, deleting ..." % g)
            del grp[g]
    else:
        print("no UV_data previously present")
    d=np.asarray(k)
    #print(d)
    dset=grp.create_dataset('[LC Chromatogram(Detector A-Ch1)]', data=d)
    dset[:]=d
    f.close()

'''
def run_single_hplc(spreadsheet_fn, sheet_name="Samples", batchID, sample_name, exp=2, shutdown=False):
    samples, valve_position = CreateAgilentSeqFile(spreadsheet_fn, batchID, sheet_name=sheet_name)
    print("Obtaining Sample and setting PV.....")
    caput('XF:16IDC-ES{HPLC}SampleName, SampleName')
'''