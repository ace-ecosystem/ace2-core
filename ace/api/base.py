# vim: ts=4:sw=4:et:cc=120
#

import io

from contextlib import contextmanager
from typing import Union, Any, Optional

from ace.analysis import RootAnalysis, AnalysisModuleType, Observable
from ace.system.analysis_request import AnalysisRequest
from ace.system.events import EventHandler
from ace.system.storage import ContentMetadata


class AceAPI:
    # alerting
    def track_alert(self, root: RootAnalysis):
        raise NotImplementedError()

    # analysis module
    def register_analysis_module_type(self, amt: AnalysisModuleType) -> AnalysisModuleType:
        raise NotImplementedError()

    def track_analysis_module_type(self, amt: AnalysisModuleType):
        raise NotImplementedError()

    def get_analysis_module_type(self, name: str) -> Union[AnalysisModuleType, None]:
        raise NotImplementedError()

    def delete_analysis_module_type(self, amt: Union[AnalysisModuleType, str]):
        raise NotImplementedError()

    def get_all_analysis_module_types(
        self,
    ) -> list[AnalysisModuleType]:
        raise NotImplementedError()

    # analysis request
    def track_analysis_request(self, request: AnalysisRequest):
        raise NotImplementedError()

    def link_analysis_requests(self, source: AnalysisRequest, dest: AnalysisRequest):
        raise NotImplementedError()

    def get_linked_analysis_requests(self, source: AnalysisRequest) -> list[AnalysisRequest]:
        raise NotImplementedError()

    def get_analysis_request_by_request_id(self, request_id: str) -> Union[AnalysisRequest, None]:
        raise NotImplementedError()

    def get_analysis_request_by_cache_key(self, cache_key: str) -> Union[AnalysisRequest, None]:
        raise NotImplementedError()

    def get_analysis_request(self, key: str) -> Union[AnalysisRequest, None]:
        raise NotImplementedError()

    def get_analysis_request_by_observable(
        self, observable: Observable, amt: AnalysisModuleType
    ) -> Union[AnalysisRequest, None]:
        raise NotImplementedError()

    def delete_analysis_request(self, target: Union[AnalysisRequest, str]) -> bool:
        raise NotImplementedError()

    def get_expired_analysis_requests(
        self,
    ) -> list[AnalysisRequest]:
        raise NotImplementedError()

    def get_analysis_requests_by_root(self, key: str) -> list[AnalysisRequest]:
        raise NotImplementedError()

    def clear_tracking_by_analysis_module_type(self, amt: AnalysisModuleType):
        raise NotImplementedError()

    def submit_analysis_request(self, ar: AnalysisRequest):
        raise NotImplementedError()

    def process_expired_analysis_requests(
        self,
    ):
        raise NotImplementedError()

    # analysis tracking
    def get_root_analysis(self, root: Union[RootAnalysis, str]) -> Union[RootAnalysis, None]:
        raise NotImplementedError()

    def track_root_analysis(self, root: RootAnalysis):
        raise NotImplementedError()

    def delete_root_analysis(self, root: Union[RootAnalysis, str]) -> bool:
        raise NotImplementedError()

    def get_analysis_details(self, uuid: str) -> Any:
        raise NotImplementedError()

    def track_analysis_details(self, root: RootAnalysis, uuid: str, value: Any) -> bool:
        raise NotImplementedError()

    def delete_analysis_details(self, uuid: str) -> bool:
        raise NotImplementedError()

    # caching
    def get_cached_analysis_result(
        self, observable: Observable, amt: AnalysisModuleType
    ) -> Union[AnalysisRequest, None]:
        raise NotImplementedError()

    def cache_analysis_result(self, request: AnalysisRequest) -> Union[str, None]:
        raise NotImplementedError()

    def delete_expired_cached_analysis_results(
        self,
    ):
        raise NotImplementedError()

    def delete_cached_analysis_results_by_module_type(self, amt: AnalysisModuleType):
        raise NotImplementedError()

    def get_total_cache_size(self, amt: Optional[AnalysisModuleType] = None):
        raise NotImplementedError()

    # config
    def get_config(self, key: str, default: Optional[Any] = None) -> Any:
        raise NotImplementedError()

    def set_config(self, key: str, value: Any):
        raise NotImplementedError()

    # events
    def register_event_handler(self, event: str, handler: EventHandler):
        raise NotImplementedError()

    def remove_event_handler(self, handler: EventHandler, events: Optional[list[str]] = []):
        raise NotImplementedError()

    def get_event_handlers(self, event: str) -> list[EventHandler]:
        raise NotImplementedError()

    def fire_event(self, event: str, *args, **kwargs):
        raise NotImplementedError()

    # locking
    def get_lock_owner(self, lock_id: str) -> Union[str, None]:
        raise NotImplementedError()

    def get_owner_wait_target(self, owner_id: str) -> Union[str, None]:
        raise NotImplementedError()

    def track_wait_target(self, lock_id: Union[str, None], owner_id: str):
        raise NotImplementedError()

    def clear_wait_target(self, owner_id: str):
        raise NotImplementedError()

    def is_locked(self, lock_id: str) -> bool:
        raise NotImplementedError()

    def get_lock_count(
        self,
    ) -> int:
        raise NotImplementedError()

    def acquire(
        self,
        lock_id: str,
        owner_id: Optional[str] = None,
        timeout: Union[int, float, None] = None,
        lock_timeout: Union[int, float, None] = None,
    ) -> bool:
        raise NotImplementedError()

    def releases(self, lock_id: str, owner_id: Optional[str] = None) -> bool:
        raise NotImplementedError()

    @contextmanager
    def lock(self, lock_id: str, timeout: Optional[float] = None, lock_timeout: Optional[float] = None):
        try:
            lock_result = acquire(lock_id, timeout=timeout, lock_timeout=lock_timeout)

            if not lock_result:
                raise LockAcquireFailed()
            else:
                yield lock_result
        finally:
            if lock_result:
                release(lock_id)

    # observables
    def create_observable(self, type: str, *args, **kwargs) -> Observable:
        raise NotImplementedError()

    # processing
    def process_analysis_request(self, ar: AnalysisRequest):
        raise NotImplementedError()

    # storage
    def store_content(self, content: Union[bytes, str, io.IOBase], meta: ContentMetadata) -> str:
        raise NotImplementedError()

    def get_content_bytes(self, sha256: str) -> Union[bytes, None]:
        raise NotImplementedError()

    def get_content_stream(self, sha256: str) -> Union[io.IOBase, None]:
        raise NotImplementedError()

    def get_content_meta(self, sha256: str) -> Union[ContentMetadata, None]:
        raise NotImplementedError()

    def delete_content(self, sha256: str) -> bool:
        raise NotImplementedError()

    def track_content_root(self, sha256: str, root: Union[RootAnalysis, str]):
        raise NotImplementedError()

    def store_file(self, path: str, **kwargs) -> str:
        """Utility function that stores the contents of the given file and returns the sha256 hash."""
        assert isinstance(path, str)
        meta = ContentMetadata(path, **kwargs)
        with open(path, "rb") as fp:
            return store_content(fp, meta)

    def get_file(self, sha256: str, path: Optional[str] = None) -> bool:
        """Utility function that pulls data out of storage into a local file. The
        original path is used unless a target path is specified."""
        assert isinstance(sha256, str)
        assert path is None or isinstance(path, str)

        meta = get_content_meta(sha256)
        if meta is None:
            return False

        if path is None:
            path = meta.name

        with open(path, "wb") as fp_out:
            with contextlib.closing(get_content_stream(sha256)) as fp_in:
                shutil.copyfileobj(fp_in, fp_out)

        return True

    # work queue
    def get_work(self, amt: Union[AnalysisModuleType, str], timeout: int) -> Union[AnalysisRequest, None]:
        raise NotImplementedError()

    def put_work(self, amt: Union[AnalysisModuleType, str], analysis_request: AnalysisRequest):
        raise NotImplementedError()

    def get_queue_size(self, amt: Union[AnalysisModuleType, str]) -> int:
        raise NotImplementedError()

    def delete_work_queue(self, amt: Union[AnalysisModuleType, str]) -> bool:
        raise NotImplementedError()

    def add_work_queue(self, amt: Union[AnalysisModuleType, str]):
        raise NotImplementedError()

    def get_next_analysis_request(
        self, owner_uuid: str, amt: Union[AnalysisModuleType, str], timeout: Optional[int] = 0
    ) -> Union[AnalysisRequest, None]:
        raise NotImplementedError()