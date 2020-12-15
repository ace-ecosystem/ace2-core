import uuid

from ace.analysis import AnalysisModuleType, RootAnalysis, Analysis
from ace.constants import *
from ace.system.analysis_module import (
    register_analysis_module_type,
    UnknownAnalysisModuleTypeError,
    CircularDependencyError,
)
from ace.system.analysis_request import AnalysisRequest, get_analysis_request
from ace.system.analysis_tracking import get_root_analysis
from ace.system.caching import get_cached_analysis_result
from ace.system.constants import TRACKING_STATUS_ANALYZING
from ace.system.inbound import process_analysis_request
from ace.system.work_queue import get_next_analysis_request, get_work_queue

import pytest

ANALYSIS_TYPE_TEST = "test"
ANALYSIS_TYPE_TEST_DEP = "test_dep"
OWNER_UUID = str(uuid.uuid4())


@pytest.mark.integration
def test_process_root_analysis_request():
    amt = AnalysisModuleType(name=ANALYSIS_TYPE_TEST, description="blah", cache_ttl=60)
    assert register_analysis_module_type(amt) == amt

    root = RootAnalysis()
    test_observable = root.add_observable(F_TEST, "test")

    root_request = root.create_analysis_request()
    process_analysis_request(root_request)

    # the root analysis should be tracked
    assert get_root_analysis(root.uuid) is not None

    # and it should not be locked
    assert not root.is_locked()

    # the test observable should be in the queue
    assert get_work_queue(amt).size() == 1
    request = get_next_analysis_request(OWNER_UUID, amt, 0)
    assert isinstance(request, AnalysisRequest)
    assert request.observable == test_observable
    assert request.type == amt
    assert request.root == root
    assert request.status == TRACKING_STATUS_ANALYZING
    assert request.owner == OWNER_UUID
    assert request.result is None

    # the original root analysis request should be deleted
    assert get_analysis_request(root_request.id) is None


@pytest.mark.integration
def test_process_duplicate_root_analysis_request():
    amt = AnalysisModuleType(name=ANALYSIS_TYPE_TEST, description="blah", cache_ttl=60)
    assert register_analysis_module_type(amt) == amt

    root = RootAnalysis()
    test_observable = root.add_observable(F_TEST, "test")

    root_request = root.create_analysis_request()
    process_analysis_request(root_request)

    # we should have a single work entry in the work queue
    assert get_work_queue(amt).size() == 1

    # make the exact same request again
    root_request = root.create_analysis_request()
    process_analysis_request(root_request)

    # should still only have one request
    assert get_work_queue(amt).size() == 1


@pytest.mark.parametrize(
    "cache_ttl",
    [
        (None),
        (60),
    ],
)
@pytest.mark.integration
def test_process_duplicate_observable_analysis_request(cache_ttl):
    amt = AnalysisModuleType(name=ANALYSIS_TYPE_TEST, description="blah", cache_ttl=cache_ttl)
    assert register_analysis_module_type(amt) == amt

    original_root = RootAnalysis()
    test_observable = original_root.add_observable(F_TEST, "test")

    root_request = original_root.create_analysis_request()
    process_analysis_request(root_request)

    # we should have a single work entry in the work queue
    assert get_work_queue(amt).size() == 1

    # make another request for the same observable but from a different root analysis
    root = RootAnalysis()
    test_observable = root.add_observable(F_TEST, "test")
    root_request = root.create_analysis_request()
    process_analysis_request(root_request)

    if cache_ttl is not None:
        # if the analysis type can be cached then there should only be one request
        # since there is already a request to analyze it
        assert get_work_queue(amt).size() == 1

        # now the existing analysis request should have a reference to the new root analysis
        request = get_next_analysis_request(OWNER_UUID, amt, 0)
        assert len(request.additional_roots) == 1
        assert root.uuid in request.additional_roots

        # process the result of the original request
        request.result = request.create_result()
        request.result.observable.add_analysis(type=amt, details={"Hello": "World"})
        process_analysis_request(request)

        # now the second root analysis should have it's analysis completed
        root = get_root_analysis(root.uuid)
        analysis = root.get_observable(test_observable).get_analysis(amt)
        assert analysis is not None
        assert analysis.root == root
        assert analysis.observable == request.observable
        assert analysis.details == request.result.observable.get_analysis(amt).details

    else:
        # otherwise there should be two requests
        assert get_work_queue(amt).size() == 2


@pytest.mark.parametrize(
    "cache_ttl",
    [
        (None),
        (60),
    ],
)
@pytest.mark.integration
def test_process_analysis_result(cache_ttl):
    amt = AnalysisModuleType(ANALYSIS_TYPE_TEST, "blah", cache_ttl=cache_ttl)
    assert register_analysis_module_type(amt) == amt

    root = RootAnalysis()
    test_observable = root.add_observable(F_TEST, "test")

    root_request = root.create_analysis_request()
    process_analysis_request(root_request)

    # get the analysis request
    request = get_next_analysis_request(OWNER_UUID, amt, 0)
    assert isinstance(request, AnalysisRequest)
    assert request.observable == test_observable
    assert request.type == amt
    assert request.root == root
    assert request.status == TRACKING_STATUS_ANALYZING
    assert request.owner == OWNER_UUID

    request.result = request.create_result()
    request.result.observable.add_analysis(type=amt, details={"Hello": "World"})
    process_analysis_request(request)

    if cache_ttl is not None:
        # this analysis result for this observable should be cached now
        assert get_cached_analysis_result(request.observable, request.type) is not None

    # get the root analysis and ensure this observable has the analysis now
    root = get_root_analysis(root.uuid)
    assert root is not None
    observable = root.get_observable_by_spec(request.observable.type, request.observable.value)
    assert observable is not None
    analysis = observable.get_analysis(request.type)
    assert analysis is not None
    assert analysis.root == root
    assert analysis.observable == request.observable
    assert analysis.details == request.result.observable.get_analysis(amt).details

    # request should be deleted
    assert get_analysis_request(request.id) is None


@pytest.mark.integration
def test_cached_analysis_result():
    amt = AnalysisModuleType(ANALYSIS_TYPE_TEST, "blah", cache_ttl=60)
    assert register_analysis_module_type(amt) == amt

    root = RootAnalysis()
    test_observable = root.add_observable(F_TEST, "test")

    root_request = root.create_analysis_request()
    process_analysis_request(root_request)

    # we should have a single work entry in the work queue
    assert get_work_queue(amt).size() == 1

    # request should be deleted
    assert get_analysis_request(root_request.id) is None

    request = get_next_analysis_request(OWNER_UUID, amt, 0)
    request.result = request.create_result()
    request.result.observable.add_analysis(type=amt, details={"Hello": "World"})
    process_analysis_request(request)

    # this analysis result for this observable should be cached now
    assert get_cached_analysis_result(request.observable, request.type) is not None

    # request should be deleted
    assert get_analysis_request(request.id) is None

    # work queue should be empty
    assert get_work_queue(amt).size() == 0

    # make another request for the same observable
    root = RootAnalysis()
    test_observable = root.add_observable(F_TEST, "test")

    root_request = root.create_analysis_request()
    process_analysis_request(root_request)

    # request should be deleted
    assert get_analysis_request(root_request.id) is None

    # work queue should be empty since the result was pulled from cache
    assert get_work_queue(amt).size() == 0

    # get the root analysis and ensure this observable has the analysis now
    root = get_root_analysis(root.uuid)
    assert root is not None
    observable = root.get_observable_by_spec(request.observable.type, request.observable.value)
    assert observable is not None
    analysis = observable.get_analysis(request.type)
    assert analysis is not None
    assert analysis.root == root
    assert analysis.observable == request.observable
    assert analysis.details == request.result.observable.get_analysis(amt).details


@pytest.mark.integration
def test_process_existing_analysis_merge():
    # register two different analysis modules
    amt_1 = AnalysisModuleType("test_1", "")
    register_analysis_module_type(amt_1)

    amt_2 = AnalysisModuleType("test_2", "")
    register_analysis_module_type(amt_2)

    root = RootAnalysis()
    test_observable = root.add_observable(F_TEST, "test")
    root.submit()

    # act like these two modules are running at the same time
    request_1 = get_next_analysis_request(OWNER_UUID, amt_1, 0)
    request_2 = get_next_analysis_request(OWNER_UUID, amt_2, 0)

    # process the first one
    request_1.result = request_1.create_result()
    request_1.result.observable.add_tag("tag_1")  # make a modification to the observable
    analysis = request_1.result.observable.add_analysis(type=amt_1)
    process_analysis_request(request_1)

    # process the second one
    request_2.result = request_2.create_result()
    analysis = request_2.result.observable.add_analysis(type=amt_2)
    process_analysis_request(request_2)

    root = get_root_analysis(root)
    test_observable = root.get_observable(test_observable)
    assert test_observable.has_tag("tag_1")
    assert test_observable.get_analysis(amt_1)
    assert test_observable.get_analysis(amt_2)


@pytest.mark.integration
def test_unknown_dependency():
    # amt_dep depends on amt which has not registered yet
    amt_dep = AnalysisModuleType(ANALYSIS_TYPE_TEST_DEP, "test", dependencies=[ANALYSIS_TYPE_TEST])
    with pytest.raises(UnknownAnalysisModuleTypeError):
        assert register_analysis_module_type(amt_dep)


@pytest.mark.integration
def test_known_dependency():
    amt = AnalysisModuleType(ANALYSIS_TYPE_TEST, "test")
    assert register_analysis_module_type(amt) == amt

    # amt_dep depends on amt
    amt_dep = AnalysisModuleType(ANALYSIS_TYPE_TEST_DEP, "test", dependencies=[ANALYSIS_TYPE_TEST])
    assert register_analysis_module_type(amt_dep)

    root = RootAnalysis()
    test_observable = root.add_observable(F_TEST, "test")

    root_request = root.create_analysis_request()
    process_analysis_request(root_request)

    # this should have one entry
    assert get_work_queue(amt).size() == 1

    # but not this one (yet) due to the dependency
    assert get_work_queue(amt_dep).size() == 0

    # process the amt request
    request = get_next_analysis_request(OWNER_UUID, amt, 0)
    request.result = request.create_result()
    request.result.observable.add_analysis(type=amt, details={"Hello": "World"})
    process_analysis_request(request)

    # now we should have a request for the dependency
    assert get_work_queue(amt_dep).size() == 1


@pytest.mark.integration
def test_chained_dependency():
    amt_1 = AnalysisModuleType("test_1", "")
    assert register_analysis_module_type(amt_1)

    # amt_2 depends on amt_1
    amt_2 = AnalysisModuleType("test_2", "", dependencies=["test_1"])
    assert register_analysis_module_type(amt_2)

    # amt_3 depends on amt_2
    amt_3 = AnalysisModuleType("test_3", "", dependencies=["test_2"])
    assert register_analysis_module_type(amt_3)

    root = RootAnalysis()
    test_observable = root.add_observable(F_TEST, "test")

    root_request = root.create_analysis_request()
    process_analysis_request(root_request)

    # this should have one entry for amt_1
    assert get_work_queue(amt_1).size() == 1

    # but not this one the others
    assert get_work_queue(amt_2).size() == 0
    assert get_work_queue(amt_3).size() == 0

    # process the amt request
    request = get_next_analysis_request(OWNER_UUID, amt_1, 0)
    request.result = request.create_result()
    request.result.observable.add_analysis(type=amt_1, details={"Hello": "World"})
    process_analysis_request(request)

    # now amt_2 should be ready but still not amt_3
    assert get_work_queue(amt_1).size() == 0
    assert get_work_queue(amt_2).size() == 1
    assert get_work_queue(amt_3).size() == 0

    # process the amt request
    request = get_next_analysis_request(OWNER_UUID, amt_2, 0)
    request.result = request.create_result()
    request.result.observable.add_analysis(type=amt_2, details={"Hello": "World"})
    process_analysis_request(request)

    # now amt_3 should be ready
    assert get_work_queue(amt_1).size() == 0
    assert get_work_queue(amt_2).size() == 0
    assert get_work_queue(amt_3).size() == 1


@pytest.mark.integration
def test_circ_dependency():
    amt_1 = AnalysisModuleType("test_1", "")
    assert register_analysis_module_type(amt_1)

    # amt_2 depends on amt_1
    amt_2 = AnalysisModuleType("test_2", "", dependencies=["test_1"])
    assert register_analysis_module_type(amt_2)

    # and now amt_1 depends on amt_2
    amt_1 = AnalysisModuleType("test_1", "", dependencies=["test_2"])
    with pytest.raises(CircularDependencyError):
        assert register_analysis_module_type(amt_1)


@pytest.mark.integration
def test_self_dependency():
    # depending on amt when amt isn' registered yet
    amt_1 = AnalysisModuleType("test_1", "", dependencies=["test_1"])
    with pytest.raises(UnknownAnalysisModuleTypeError):
        assert register_analysis_module_type(amt_1)

    # define it
    amt_1 = AnalysisModuleType("test_1", "")
    assert register_analysis_module_type(amt_1)

    # redefine to depend on yourself
    # cannot depend on yourself! (low self esteem error)
    amt_1 = AnalysisModuleType("test_1", "", dependencies=["test_1"])
    with pytest.raises(CircularDependencyError):
        assert register_analysis_module_type(amt_1)


@pytest.mark.integration
def test_cancel_analysis_from_result():
    amt = AnalysisModuleType("test", "")
    register_analysis_module_type(amt)

    root = RootAnalysis()
    observable = root.add_observable("test", "test")

    request = root.create_analysis_request()
    process_analysis_request(request)

    # get the analysis request
    request = get_next_analysis_request(OWNER_UUID, amt, 0)
    request.result = request.create_result()
    analysis = request.result.observable.add_analysis(type=amt, details={"Hello": "World"})
    new_observable = analysis.add_observable("new", "new")
    request.result.root.cancel_analysis("test")
    process_analysis_request(request)

    # root analysis should be cancelled
    root = get_root_analysis(root.uuid)
    assert root.analysis_cancelled
    assert root.analysis_cancelled_reason == "test"

    # we should still have the analysis and the new observable we added in that result
    observable = root.get_observable(observable)
    analysis = observable.get_analysis(amt)
    assert analysis is not None
    new_observable = root.get_observable(new_observable)
    assert new_observable is not None

    # we should not have any new work requests since the analysis was cancelled
    assert get_work_queue(amt).size() == 0


@pytest.mark.integration
def test_cancel_analysis():
    amt = AnalysisModuleType("test", "")
    register_analysis_module_type(amt)

    root = RootAnalysis()
    observable = root.add_observable("test", "test")

    request = root.create_analysis_request()
    process_analysis_request(request)

    # before we work the queue we update the root to cancel analysis
    root = get_root_analysis(root)
    root.cancel_analysis("test")
    process_analysis_request(root.create_analysis_request())

    root = get_root_analysis(root)
    assert root.analysis_cancelled
    assert root.analysis_cancelled_reason == "test"

    # now work the queue
    request = get_next_analysis_request(OWNER_UUID, amt, 0)
    # now it doesn't say it's cancelled here because this was created before we cancelled it
    assert not request.root.analysis_cancelled
    # post our results
    request.result = request.create_result()
    analysis = request.result.observable.add_analysis(type=amt, details={"Hello": "World"})
    new_observable = analysis.add_observable("new", "new")
    request.result.root.cancel_analysis("test")
    process_analysis_request(request)

    # root analysis should be cancelled here since this a fresh request
    root = get_root_analysis(root.uuid)
    assert root.analysis_cancelled
    assert root.analysis_cancelled_reason == "test"

    # we should still have the analysis and the new observable we added in that result
    observable = root.get_observable(observable)
    analysis = observable.get_analysis(amt)
    assert analysis is not None
    new_observable = root.get_observable(new_observable)
    assert new_observable is not None

    # we should not have any new work requests since the analysis was cancelled
    assert get_work_queue(amt).size() == 0
