# vim: ts=4:sw=4:et:cc=120
#
# threaded implementation of the ACE Engine
# useful for unit testing
#

import threading

class ThreadedInterface():
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sync_lock = threading.RLock()

from ace.system import ACESystem, set_system
from ace.system.threaded.analysis_module import ThreadedAnalysisModuleTrackingInterface
from ace.system.threaded.analysis_request import ThreadedAnalysisRequestTrackingInterface
from ace.system.threaded.analysis_tracking import ThreadedAnalysisTrackingInterface
from ace.system.threaded.config import ThreadedConfigurationInterface
from ace.system.threaded.caching import ThreadedCachingInterface
from ace.system.threaded.locking import ThreadedLockingInterface
from ace.system.threaded.observables import ThreadedObservableInterface
from ace.system.threaded.storage import ThreadedStorageInterface
from ace.system.threaded.work_queue import ThreadedWorkQueueManagerInterface

class ThreadedACESystem(ACESystem):
    work_queue = ThreadedWorkQueueManagerInterface()
    request_tracking = ThreadedAnalysisRequestTrackingInterface()
    module_tracking = ThreadedAnalysisModuleTrackingInterface()
    analysis_tracking = ThreadedAnalysisTrackingInterface()
    caching = ThreadedCachingInterface()
    storage = ThreadedStorageInterface()
    locking = ThreadedLockingInterface()
    observable = ThreadedObservableInterface()
    config = ThreadedConfigurationInterface()

    def reset(self):
        self.work_queue.reset()
        self.request_tracking.reset()
        self.module_tracking.reset()
        self.analysis_tracking.reset()
        self.caching.reset()
        self.storage.reset()
        self.locking.reset()
        self.config.reset()

def initialize():
    set_system(ThreadedACESystem())
