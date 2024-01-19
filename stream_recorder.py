"""
A light weight recorder that can record in a non-stop fashion.
The recorded signal is saved to a file at a specified interval (default to 300 secs).
The audio format is mono, 16-bit linear PCM, with the sampling frequency 
    being configurable (default to 16_000 Hz).

External recording device tested: EVO8, FocusRite (as well as MacBook built-in)

Author: Q. Lin
Jan 2024

Testing from Mac:
    python3 stream_recorder.py -r 16000 -d 5

Note:
    If running on Mac and encountering this error:
    Exception=Error opening InputStream: Internal PortAudio error [PaErrorCode -9986]
    A simple way to solve this problem is to run 
      $> rec temp.wav
    from the command line and it will prompt you to allow Terminal to access the mic.
    Or you can add the access to mic through direct configuring system preference.

Note:
    If -d <device> is absent, the default (device=None) device of the system is used.
"""

import sys
import os
import wave
from datetime import datetime, date

import sounddevice as sd
import logging as LOG
from getopt import getopt
import numpy as np

class CFG:
    '''Class to contain config parameters with default values'''
    def __init__(self):
        self.fs = 16000        # Sampling frequency in Hz
        self.channels = 1      # only mono is supported in this version
        self.dura = 300        # duration of the recorded file (default 300 secs)
        self.device_name = ''  # use -q to query device available
        self.device_index = -1 # ditto
        self.blocksize = 1024  # 0.064 secs for fs = 16000 Hz.
        self.query_device = False # to query about recording device
        self.audio_file_path = 'audio_data' # folder name for audio files
        self.log_file_path = 'logs'         # falder name for log files
        self.end_time = '23:59' # time to end record daily. Use cronjob for the start time
                                # set it to '-1:0' to record forever

def usage():
    print(f'{sys.argv[0]} [-h] [-q] [-a <audio_file_path>] [-l <log_file_path>]',
        '[-r <rate>] [-d <device>] [-b <blocksize>] [-D <dura>] [-e end_time')
    print('   where <rate> is the sampling frequency in Hz')
    print('   -h to print this help page')
    print('   -q is to query recording device (hardware) to help you select a device')
    print('   for <dura> (duration in secs), the short version is uppercased -D')
    print('   and <device> can be an integer (device_index) or a string (device_name).')
    sys.exit(0)

def parse_cmdline(argv):
    '''parse the command line.'''
    cfg = CFG()

    try:
        opts, args = getopt(argv, "hqa:l:r:d:b:e:D:", 
            ['audio_file_path=', 'log_file_path=', 'rate=', 'device=', 'blocksize=', 'end_time=', 'dura='])
    except getopt.GetoptError as e:
        print('getopt error in parse_cmdline(): ', e)
        usage()

    try:
        for opt, arg in opts:
            if opt in ("-h"):
                usage()
            elif opt in ("-r", "--rate"):
                cfg.fs = int(arg)
            elif opt in ("-d", "--device"):
                try:
                    cfg.device_index = int(arg)
                    #print('device_index was given')
                except:
                    cfg.device_name = arg
                    #print('device_name was given')
            elif opt in ("-b", "--blocksize"):
                cfg.blocksize = int(arg)
            elif opt in ("-D", "--dura"):
                cfg.dura = float(arg)
            elif opt in ("-e", "--end_time"):
                cfg.end_time = arg
            elif opt in ("-q"):
                cfg.query_device = True
            elif opt in ("-a", "--audio_file_path"):
                cfg.audio_file_path = arg
            elif opt in ("-l", "--log_file_path"):
                cfg.log_file_path = arg
    except ValueError as e:
        print(f'ValueError: {e}. Please check the command line.')
        usage()

    return cfg

def mkdir_folder(folder_name):
    if os.path.exists(folder_name):
        LOG.info(f'path {folder_name} exists')
    else:
        LOG.warning(f'path {folder_name} does not exist')
        os.makedirs(folder_name)  # similar to "mkdir -p"
    return

def setup_log(LOG):
    LOG.basicConfig(filename=f'{cfg.log_file_path}{os.path.sep}stream_recorder.log',
                filemode='a',
                level=LOG.INFO,
                format='%(asctime)s %(levelname)s: %(message)s')
    return LOG 

def callback(indata, frames, timeinfo, status):
    '''This is called for each recorded audio block'''
    if status:
        print(status)
        LOG.error(f'status={status}')
    global audio_buffer
    audio_buffer = indata.copy()

def stream_record(daily_path='', session=0, frames=4_800_000, cfg=None):
    fname_trunk = '{:%Y%m%dh%Hm%M}'.format(datetime.now())  # Note the colon token
    fname = f'{daily_path}{os.path.sep}{fname_trunk}S{session:02d}.wav'
    LOG.info(f'recording session: {session} {fname=}')
    wf = wave.open(fname, 'wb')
    wf.setnchannels(cfg.channels)
    wf.setsampwidth(2)
    wf.setframerate(cfg.fs)

    global audio_buffer
    n_frames = 0
    print_instants = [int(x) for x in np.linspace(0, frames, 10)]
    next_mark = 0.
    delta_mark = 20.
    while n_frames < frames:
        while True:
            if audio_buffer.shape[0] == cfg.blocksize:
                break

        buf = audio_buffer[:, 0]
        # reset audio_buffer. Don't add too much process here to avoid racing conditions
        audio_buffer = np.array([]).reshape(0, 1)

        if buf.dtype != np.int16:
            '''Convert it to 16-bit integers (aka shorts)'''
            buf *= 32768
            buf = buf.astype(np.int16)

        completed = n_frames*100./frames
        if completed >= next_mark:
            next_mark += delta_mark
            print(f'\r>> Completing {(n_frames*100./frames):.1f}%...', end='')

        n_frames += buf.shape[0]
        wf.writeframes(b''.join(buf))
    
    print('\r>> Completed 100.% session='+str(session))
    wf.close() # done with a particular session

    return

def main(argv):
    if cfg.query_device:
        device = sd.query_devices(kind='input')
        print('Available device for INPUT (recording):\n', device)
        sys.exit(0)

    if cfg.dura <= 0:
        print(f'Length of recording is bad ({cfg.dura}).')
        sys.exit(1)

    if cfg.device_name == '' and cfg.device_index != -1:
        device = cfg.device_index
    elif cfg.device_name != '': 
        device = cfg.device_name
    else:
        device = None
    print(f'device={device}')

    stream = None
    for dtype in ['float32', 'float24', 'int16']:
        try:
            stream = sd.InputStream(
                samplerate=cfg.fs,
                blocksize=cfg.blocksize,
                channels=cfg.channels, # Only support mono in this version
                dtype=dtype,
                device=device,
                clip_off=False,
                callback=callback,
                )
            break  # either float32/24 or int16 works (in this order)
        except Exception as e:
            if dtype == 'float32' or dtype == 'float24':
                print(f'The recording device does not support {dtype}. Trying another now', file=sys.stderr)
                LOG.warning(f'The recording device does not support {dtype}.')
            else:
                print('The recording device does not support int16 either', file=sys.stderr)
                LOG.warning('The recording device does not support int16 either')
            LOG.warning(f'Exception={e}')
            continue
    else:
        print(f'{"*"*10} Recording stream failed to open {"*"*10}', file=sys.stderr)
        LOG.error(f'{"*"*10} Recording stream failed to open {"*"*10}')
        LOG.shutdown()
        sys.exit(1)

    print('Recording stream created successfully', device, dtype)
    LOG.StreamHandler().flush()

    # Ready to take off!
    try:
        stream.start()
        session = 0
        frames = int(cfg.dura * cfg.fs)
        end_time = cfg.end_time.strip().split(':')
        end_time_hour, end_time_minute = int(end_time[0]), int(end_time[1])
        current_day = -1

        while True:
            tid = datetime.now()
            if '{:%Y%m%d}'.format(tid) != current_day:
                current_day = '{:%Y%m%d}'.format(date.today())
                daily_path = f'{cfg.audio_file_path}{os.path.sep}{current_day}'
                mkdir_folder(daily_path)
            if (tid.hour != -1 and tid.hour > end_time_hour) or \
                (tid.hour == end_time_hour and tid.minute >= end_time_minute):
                # tid.hour = -1 will run this script forever (beyond this day)
                break

            stream_record(daily_path=daily_path, session=session, frames=frames, cfg=cfg)
            LOG.StreamHandler().flush()
            session += 1

    except KeyboardInterrupt:
        LOG.warning('Received a KeyboardInterrupt')
        print('\nReceived a KeyboardInterrupt', file=sys.stderr)

    else:
        try:
            stream.stop()
            stream.close()
        except:
            pass
        LOG.warning('Recording time is up')
        print('\nRecording time is up\nDONE', file=sys.stderr)

    try:
        stream.stop()
        stream.close()
        LOG.shutdown()
    except:
        pass

if __name__ == "__main__":
    # set up the "global" logger
    cfg = parse_cmdline(sys.argv[1:])

    if not os.path.exists(cfg.log_file_path):
        os.makedirs(cfg.log_file_path)

    LOG = setup_log(LOG)
    LOG.info(f'Working directory is {os.getcwd()}')
    mkdir_folder(cfg.audio_file_path)

    # initialization
    audio_buffer = np.array([]).reshape(0, 1)

    main(sys.argv[:])

