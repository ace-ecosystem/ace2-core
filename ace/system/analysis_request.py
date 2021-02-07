# vim: ts=4:sw=4:et:cc=120

import copy
import logging
import uuid
from typing import Union, List, Optional, Any

from ace.analysis import RootAnalysis, Observable
from ace.data_model import AnalysisRequestModel, RootAnalysisModel
from ace.system import ACESystemInterface, get_system
from ace.system.analysis_tracking import get_root_analysis
from ace.system.analysis_module import AnalysisModuleType, UnknownAnalysisModuleTypeError
from ace.system.constants import (
    TRACKING_STATUS_NEW,
    TRACKING_STATUS_QUEUED,
    SYSTEM_LOCK_EXPIRED_ANALYSIS_REQUESTS,
    EVENT_AR_NEW,
    EVENT_AR_DELETED,
    EVENT_AR_EXPIRED,
)
from ace.system.events import fire_event


class AnalysisRequest:
    """Represents a request to analyze a single observable or a new analysis."""

    def __init__(
        self,
        root: Union[str, RootAnalysis],
        observable: Optional[Observable] = None,
        type: Optional[AnalysisModuleType] = None,
    ):

        from ace.system.caching import generate_cache_key

        assert isinstance(root, RootAnalysis) or isinstance(root, str)
        assert isinstance(observable, Observable) or observable is None
        assert isinstance(type, AnalysisModuleType) or type is None

        # load existing analysis if root is passed in as a string uuid
        if isinstance(root, str):
            self.root = get_root_analysis(root)
        else:
            self.root = root

        #
        # static data
        #

        # generic unique ID of the request
        self.id = str(uuid.uuid4())
        # the Observable to be analyzed
        self.observable = observable
        # the type of analysis module to execute on this observable
        self.type = type
        # the key used to cache the analysis result
        # if this is a root analysis request or if the amt does not support caching then this is None
        self.cache_key = generate_cache_key(self.observable, self.type)
        # the RootAnalysis object this request belongs to or is entirely about
        # this can also be the UUID of the RootAnalysis
        # dict of analysis dependencies requested
        # key = analysis_module, value = Analysis
        self.dependency_analysis = {}
        # set to True if this observable analysis result is the result of a cache hit
        self.cache_hit = False

        #
        # dynamic data
        #

        # the current status of this analysis request
        self.status = TRACKING_STATUS_NEW
        # the UUID of the analysis module that is currently processing this request
        self.owner = None

        # the result of the analysis
        self.original_root = None
        self.modified_root = None

    def __eq__(self, other):
        if not isinstance(other, AnalysisRequest):
            return False

        return self.id == other.id

    def __str__(self):
        return f"AnalysisRequest(id={self.id},root={self.root},observable={self.observable},type={self.type})"

    def to_model(self, *args, **kwargs) -> AnalysisRequestModel:
        return AnalysisRequestModel(
            id=self.id,
            root=self.root if isinstance(self.root, str) else self.root.to_model(*args, **kwargs),
            observable=self.observable.to_model(*args, **kwargs) if self.observable else None,
            type=self.type.to_model(*args, **kwargs) if self.type else None,
            status=self.status,
            owner=self.owner,
            original_root=self.original_root.to_model(*args, **kwargs) if self.original_root else None,
            modified_root=self.modified_root.to_model(*args, **kwargs) if self.modified_root else None,
        )

    def to_dict(self, *args, **kwargs) -> dict:
        return self.to_model(*args, **kwargs).dict()

    def to_json(self, *args, **kwargs) -> str:
        return self.to_model(*args, **kwargs).json()

    @staticmethod
    def from_dict(value: dict) -> "AnalysisRequest":
        assert isinstance(value, dict)

        data = AnalysisRequestModel(**value)

        root = None
        if isinstance(data.root, RootAnalysisModel):
            root = RootAnalysis.from_dict(data.root.dict())

        observable = None
        if data.observable:
            observable = Observable.from_dict(data.observable.dict(), root)
            observable = root.get_observable(observable)

        type = None
        if data.type:
            type = AnalysisModuleType.from_dict(data.type.dict())

        ar = AnalysisRequest(root, observable, type)
        ar.id = data.id
        # ar.dependency_analysis = json_data["dependency_analysis"]
        ar.status = data.status
        ar.owner = data.owner

        if data.original_root:
            ar.original_root = RootAnalysis.from_dict(data.original_root.dict())

        if data.modified_root:
            ar.modified_root = RootAnalysis.from_dict(data.modified_root.dict())

        return ar

    @staticmethod
    def from_json(value: str) -> "AnalysisRequest":
        assert isinstance(value, str)
        return AnalysisRequest.from_dict(AnalysisRequestModel.parse_raw(value).dict())

    #
    # utility functions
    #

    @property
    def is_cachable(self):
        """Returns True if the result of the analysis should be cached."""
        return self.cache_key is not None

    @property
    def is_observable_analysis_request(self) -> bool:
        """Was this a request to analyze an Observable?"""
        return self.observable is not None

    @property
    def is_observable_analysis_result(self) -> bool:
        """Does this include the result of the analysis?"""
        return self.result is not None

    @property
    def is_root_analysis_request(self) -> bool:
        """Was this a request to analyze a RootAnalysis?"""
        return self.observable is None

    @property
    def observables(self) -> List[Observable]:
        """Returns the list of all observables to analyze."""
        if self.is_observable_analysis_request:
            if self.is_observable_analysis_result:
                # process both the new observables and the one we already processed
                # doing so resolves dependencies
                observables = self.modified_observable.get_analysis(self.type).observables[:]
                observables.append(self.modified_observable)
                return observables
            else:
                # otherwise we just want to look at the observable
                return [self.observable]
        else:
            # otherwise we analyze all the observables in the entire RootAnalysis
            return self.root.all_observables

    @property
    def result(self):
        """Returns the RootAnalysis object that contains the results for this analysis."""
        return self.modified_root

    @property
    def modified_observable(self):
        """Returns a reference to the observable instance to use to store analysis results."""
        if self.modified_root is None:
            return None

        return self.modified_root.get_observable(self.observable)

    def initialize_result(self):
        """Initializes the results for this request."""
        self.original_root = copy.deepcopy(self.root)
        self.modified_root = copy.deepcopy(self.root)
        return self.result

    def submit(self):
        """Submits this analysis request for processing."""
        submit_analysis_request(self)

    def lock(self) -> bool:
        return lock_analysis_request(self)

    def unlock(self) -> bool:
        return unlock_analysis_request(self)


class AnalysisRequestTrackingInterface(ACESystemInterface):
    """Tracks and manages analysis requests."""

    def track_analysis_request(self, request: AnalysisRequest):
        raise NotImplementedError()

    def lock_analysis_request(self, request: AnalysisRequest) -> bool:
        raise NotImplementedError()

    def link_analysis_requests(self, source_request: AnalysisRequest, dest_request: AnalysisRequest) -> bool:
        raise NotImplementedError()

    def get_linked_analysis_requests(self, source: AnalysisRequest) -> list[AnalysisRequest]:
        raise NotImplementedError()

    def delete_analysis_request(self, key: str) -> bool:
        raise NotImplementedError()

    def get_expired_analysis_requests(self) -> List[AnalysisRequest]:
        raise NotImplementedError()

    def get_analysis_request_by_request_id(self, key: str) -> Union[AnalysisRequest, None]:
        raise NotImplementedError()

    def get_analysis_request_by_cache_key(self, key: str) -> Union[AnalysisRequest, None]:
        raise NotImplementedError()

    def get_analysis_requests_by_root(self, key: str) -> list[AnalysisRequest]:
        raise NotImplementedError()

    def clear_tracking_by_analysis_module_type(self, amt: AnalysisModuleType):
        raise NotImplementedError()

    def process_expired_analysis_requests(self, amt: AnalysisModuleType):
        raise NotImplementedError()


def track_analysis_request(request: AnalysisRequest):
    """Begins tracking the given AnalysisRequest."""
    assert isinstance(request, AnalysisRequest)
    from ace.system.analysis_module import get_analysis_module_type

    if request.type and get_analysis_module_type(request.type.name) is None:
        raise UnknownAnalysisModuleTypeError(request.type.name)

    logging.debug(f"tracking analysis request {request}")
    result = get_system().request_tracking.track_analysis_request(request)
    fire_event(EVENT_AR_NEW, request)
    return result


def lock_analysis_request(request: AnalysisRequest) -> bool:
    """Attempts to lock the request. Returns True if successful, False otherwise.
    A request that is locked should not be modified by a process that did not acquire the lock."""
    assert isinstance(request, AnalysisRequest)
    return get_system().request_tracking.lock_analysis_request(request)


def unlock_analysis_request(request: AnalysisRequest) -> bool:
    assert isinstance(request, AnalysisRequest)
    return get_system().request_tracking.unlock_analysis_request(request)


def link_analysis_requests(source_request: AnalysisRequest, dest_request: AnalysisRequest) -> bool:
    assert isinstance(source_request, AnalysisRequest)
    assert isinstance(dest_request, AnalysisRequest)
    assert source_request != dest_request
    logging.debug(f"linking analysis request source {source_request} to dest {dest_request}")
    return get_system().request_tracking.link_analysis_requests(source_request, dest_request)


def get_linked_analysis_requests(source_request: AnalysisRequest) -> list[AnalysisRequest]:
    assert isinstance(source_request, AnalysisRequest)
    return get_system().request_tracking.get_linked_analysis_requests(source_request)


def get_analysis_request_by_request_id(request_id: str) -> Union[AnalysisRequest, None]:
    return get_system().request_tracking.get_analysis_request_by_request_id(request_id)


def get_analysis_request_by_cache_key(cache_key: str) -> Union[AnalysisRequest, None]:
    return get_system().request_tracking.get_analysis_request_by_cache_key(cache_key)


def get_analysis_request(key: str) -> Union[AnalysisRequest, None]:
    return get_analysis_request_by_request_id(key)


def get_analysis_request_by_observable(observable: Observable, amt: AnalysisModuleType) -> Union[AnalysisRequest, None]:
    from ace.system.caching import generate_cache_key

    cache_key = generate_cache_key(observable, amt)
    if cache_key is None:
        return None

    return get_analysis_request_by_cache_key(cache_key)


def delete_analysis_request(target: Union[AnalysisRequest, str]) -> bool:
    assert isinstance(target, AnalysisRequest) or isinstance(target, str)
    if isinstance(target, AnalysisRequest):
        target = target.id

    logging.debug(f"deleting analysis request {target}")
    result = get_system().request_tracking.delete_analysis_request(target)
    if result:
        fire_event(EVENT_AR_DELETED, target)
    return result


def get_expired_analysis_requests() -> List[AnalysisRequest]:
    """Returns all AnalysisRequests that are in the TRACKING_STATUS_ANALYZING state and have expired."""
    return get_system().request_tracking.get_expired_analysis_requests()


def get_analysis_requests_by_root(key: str) -> list[AnalysisRequest]:
    """Returns all requests assigned to the given root analysis."""
    return get_system().request_tracking.get_analysis_requests_by_root(key)


def clear_tracking_by_analysis_module_type(amt: AnalysisModuleType):
    """Deletes tracking for any requests assigned to the given analysis module type."""
    logging.debug(f"clearing analysis request tracking for analysis module type {amt}")
    return get_system().request_tracking.clear_tracking_by_analysis_module_type(amt)


def submit_analysis_request(ar: AnalysisRequest):
    """Submits the given AnalysisRequest to the appropriate queue for analysis."""
    from ace.system.processing import process_analysis_request
    from ace.system.work_queue import put_work

    assert isinstance(ar, AnalysisRequest)
    assert isinstance(ar.root, RootAnalysis)

    ar.owner = None
    ar.status = TRACKING_STATUS_QUEUED
    unlock_analysis_request(ar)
    track_analysis_request(ar)

    # if this is a RootAnalysis request then we just process it here (there is no inbound queue for root analysis)
    if ar.is_root_analysis_request or ar.is_observable_analysis_result:
        return process_analysis_request(ar)

    # otherwise we assign this request to the appropriate work queue based on the amt
    put_work(ar.type, ar)


def process_expired_analysis_requests(amt: AnalysisModuleType):
    """Moves all unlocked expired analysis requests back into the queue."""
    assert isinstance(amt, AnalysisModuleType)
    return get_system().request_tracking.process_expired_analysis_requests(amt)
