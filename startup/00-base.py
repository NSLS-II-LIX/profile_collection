print(f"Loading {__file__}...")

###############################################################################
# TODO: remove this block once https://github.com/bluesky/ophyd/pull/959 is
# merged/released.
from datetime import datetime
from ophyd.signal import EpicsSignalBase, EpicsSignal, DEFAULT_CONNECTION_TIMEOUT

def print_now():
    return datetime.strftime(datetime.now(), '%Y-%m-%d %H:%M:%S.%f')

def wait_for_connection_base(self, timeout=DEFAULT_CONNECTION_TIMEOUT):
    '''Wait for the underlying signals to initialize or connect'''
    if timeout is DEFAULT_CONNECTION_TIMEOUT:
        timeout = self.connection_timeout
    # print(f'{print_now()}: waiting for {self.name} to connect within {timeout:.4f} s...')
    start = time.time()
    try:
        self._ensure_connected(self._read_pv, timeout=timeout)
        # print(f'{print_now()}: waited for {self.name} to connect for {time.time() - start:.4f} s.')
    except TimeoutError:
        if self._destroyed:
            raise DestroyedError('Signal has been destroyed')
        raise

def wait_for_connection(self, timeout=DEFAULT_CONNECTION_TIMEOUT):
    '''Wait for the underlying signals to initialize or connect'''
    if timeout is DEFAULT_CONNECTION_TIMEOUT:
        timeout = self.connection_timeout
    # print(f'{print_now()}: waiting for {self.name} to connect within {timeout:.4f} s...')
    start = time.time()
    self._ensure_connected(self._read_pv, self._write_pv, timeout=timeout)
    # print(f'{print_now()}: waited for {self.name} to connect for {time.time() - start:.4f} s.')

EpicsSignalBase.wait_for_connection = wait_for_connection_base
EpicsSignal.wait_for_connection = wait_for_connection
###############################################################################

from ophyd.signal import EpicsSignalBase
# EpicsSignalBase.set_default_timeout(timeout=10, connection_timeout=10)  # old style
EpicsSignalBase.set_defaults(timeout=10, connection_timeout=10)  # new style

import faulthandler
faulthandler.enable()
import logging
import sys

from bluesky.run_engine import RunEngine
import nslsii
import redis
from redis_json_dict import RedisJSONDict

uri = "info.lix.nsls2.bnl.gov"
new_md = RedisJSONDict(redis.Redis(uri), prefix="")

class CustomRunEngine(RunEngine):
    def __call__(self, *args, **kwargs):
        global username
        global proposal_id
        global run_id

        if username is None or proposal_id is None or run_id is None:
            login()

        return super().__call__(*args, **kwargs)

RE = CustomRunEngine()

nslsii.configure_base(get_ipython().user_ns, 'lix', bec=True, pbar=False, publish_documents_with_kafka=True)

def reload_macros(file):
    ipy = get_ipython()
    ipy.run_line_magic('run', f'-i {ipy.profile_dir.location}/startup/{file}')


def is_ipython():
    ip = True
    if 'ipykernel' in sys.modules:
        ip = False # Notebook
    elif 'IPython' in sys.modules:
        ip = True # Shell
    return ip


# def setup_LIX(user_ns, mode):
#     ns = {}
#     ns.update(lix_base())
#     if mode == 'scanning':
#         user_ns['motor'] = EpicsMotor(...)
# 
#     elif mode == 'solution':
#         ...
# 
#     user_ns.update(ns)
#     return list(ns)
# 
# 
# def new_login():
#     ...
# 
#     setup_LIX(ip.user_ns, ...)


# this is for backward compatibility with bluesky 1.5.x
# eventually this will be removed
#from pathlib import Path
#
#import appdirs
#
#
#try:
#    from bluesky.utils import PersistentDict
#except ImportError:
#    import msgpack
#    import msgpack_numpy
#    import zict
#
#    class PersistentDict(zict.Func):
#        """
#        A MutableMapping which syncs it contents to disk.
#        The contents are stored as msgpack-serialized files, with one file per item
#        in the mapping.
#        Note that when an item is *mutated* it is not immediately synced:
#        >>> d['sample'] = {"color": "red"}  # immediately synced
#        >>> d['sample']['shape'] = 'bar'  # not immediately synced
#        but that the full contents are synced to disk when the PersistentDict
#        instance is garbage collected.
#        """
#        def __init__(self, directory):
#            self._directory = directory
#            self._file = zict.File(directory)
#            self._cache = {}
#            super().__init__(self._dump, self._load, self._file)
#            self.reload()
#
#            # Similar to flush() or _do_update(), but without reference to self
#            # to avoid circular reference preventing collection.
#            # NOTE: This still doesn't guarantee call on delete or gc.collect()!
#            #       Explicitly call flush() if immediate write to disk required.
#            def finalize(zfile, cache, dump):
#                zfile.update((k, dump(v)) for k, v in cache.items())
#
#            import weakref
#            self._finalizer = weakref.finalize(
#                self, finalize, self._file, self._cache, PersistentDict._dump)
#
#        @property
#        def directory(self):
#            return self._directory
#
#        def __setitem__(self, key, value):
#            self._cache[key] = value
#            super().__setitem__(key, value)
#
#        def __getitem__(self, key):
#            return self._cache[key]
#
#        def __delitem__(self, key):
#            del self._cache[key]
#            super().__delitem__(key)
#
#        def __repr__(self):
#            return f"<{self.__class__.__name__} {dict(self)!r}>"
#
#        @staticmethod
#        def _dump(obj):
#            "Encode as msgpack using numpy-aware encoder."
#            # See https://github.com/msgpack/msgpack-python#string-and-binary-type
#            # for more on use_bin_type.
#            return msgpack.packb(
#                obj,
#                default=msgpack_numpy.encode,
#                use_bin_type=True)
#
#        @staticmethod
#        def _load(file):
#            return msgpack.unpackb(
#                file,
#                object_hook=msgpack_numpy.decode,
#                raw=False)
#
#        def flush(self):
#            """Force a write of the current state to disk"""
#            for k, v in self.items():
#                super().__setitem__(k, v)
#
#        def reload(self):
#            """Force a reload from disk, overwriting current cache"""
#            self._cache = dict(super().items())
#
#runengine_metadata_dir = appdirs.user_data_dir(appname="bluesky") / Path("runengine-metadata")
#
## PersistentDict will create the directory if it does not exist
#RE.md = PersistentDict(runengine_metadata_dir)

RE.md = new_md

import re
import warnings

import httpx


def md_validator(md):
    "Ensure that if data_session is specified it is valid>"
    PATTERN = re.compile("^pass-[0-9]+$")
    data_session = md.get("data_session")
    if data_session is None:
        return

    print(data_session)
    return

    if (not isinstance(data_session, str)) or (not PATTERN.match(data_session)):
        raise ValueError("data_session must be a string formed like 'pass-NUMBER', as in 'pass-123456'.")
    try:
        client = httpx.Client(base_url="https://api.nsls2.bnl.gov")
        #client = httpx.Client(base_url="https://api-staging.nsls2.bnl.gov")
        response = client.get(f"/proposal/{data_session[5:]}")    
    except Exception:
        warnings.warn("Could not connect to API to verify data_session is valid.")
        return
    if response.is_client_error:
        raise ValueError(MSG)
    if response.is_error:
        warnings.warn("Could not confirm with API that data_session is valid.")
    elif "error_message" in response.json():
        raise ValueError(f"data_session {data_session} could not be found.")


RE.md_validator = md_validator
