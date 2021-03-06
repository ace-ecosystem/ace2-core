import uuid

from ace.analysis import AnalysisModuleType, RootAnalysis, Analysis
from ace.system.requests import AnalysisRequest
from ace.constants import TRACKING_STATUS_ANALYZING
from ace.exceptions import (
    AnalysisModuleTypeDependencyError,
    UnknownAnalysisModuleTypeError,
    CircularDependencyError,
)

import pytest

ANALYSIS_TYPE_TEST = "test"
ANALYSIS_TYPE_TEST_DEP = "test_dep"
OWNER_UUID = str(uuid.uuid4())


@pytest.mark.asyncio
@pytest.mark.integration
async def test_all_analysis_completed(system):
    amt = AnalysisModuleType(name=ANALYSIS_TYPE_TEST, description="blah", cache_ttl=60)
    assert await system.register_analysis_module_type(amt) == amt

    root = system.new_root()
    test_observable = root.add_observable("test", "test")
    # this is technically correct because the root has not been presented to a core yet
    assert root.all_analysis_completed()

    await root.submit()
    # now this is False because we have an outstanding analysis request
    root = await system.get_root_analysis(root)
    assert not root.all_analysis_completed()

    request = await system.get_next_analysis_request("test", amt, 0)
    request.initialize_result()
    request.modified_observable.add_analysis(type=amt, details={"Hello": "World"})
    await request.submit()

    # and then finally the root is complete once all requested analysis is present
    root = await system.get_root_analysis(root)
    assert root.all_analysis_completed()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_process_root_analysis_request(system):
    amt = AnalysisModuleType(name=ANALYSIS_TYPE_TEST, description="blah", cache_ttl=60)
    assert await system.register_analysis_module_type(amt) == amt
    assert await system.get_queue_size(amt) == 0

    root = system.new_root()
    test_observable = root.add_observable("test", "test")

    root_request = root.create_analysis_request()
    await system.process_analysis_request(root_request)

    # the root analysis should be tracked
    assert await system.get_root_analysis(root.uuid) is not None

    # the test observable should be in the queue
    assert await system.get_queue_size(amt) == 1
    request = await system.get_next_analysis_request(OWNER_UUID, amt, 0)
    assert isinstance(request, AnalysisRequest)
    assert request.observable == test_observable
    assert request.type == amt
    assert request.root.uuid == root.uuid and request.root.version is not None
    assert request.status == TRACKING_STATUS_ANALYZING
    assert request.owner == OWNER_UUID
    assert request.result is None

    # the original root analysis request should be deleted
    assert await system.get_analysis_request(root_request.id) is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_process_parallel_root_analysis_request(monkeypatch, system):
    amt = AnalysisModuleType(name=ANALYSIS_TYPE_TEST, description="blah", cache_ttl=60)
    assert await system.register_analysis_module_type(amt) == amt

    root = system.new_root()
    test_observable = root.add_observable("test", "test")

    root_request = root.create_analysis_request()
    await system.process_analysis_request(root_request)

    # the root analysis should be tracked
    assert await system.get_root_analysis(root.uuid) is not None

    # get the current version of the root
    old_root = await system.get_root_analysis(root)

    original_get_root_analysis = system.get_root_analysis
    trigger = False

    async def hacked_get_root_analysis(_root):
        nonlocal root
        nonlocal original_get_root_analysis
        nonlocal trigger

        result = await original_get_root_analysis(_root)
        if trigger:
            return result

        # only do this once
        trigger = True

        # modify the root right after we get it
        if isinstance(_root, RootAnalysis):
            _root = _root.uuid

        root = await system.get_root_analysis(_root)
        await root.save()

        return result

    with monkeypatch.context() as m:
        m.setattr(system, "get_root_analysis", hacked_get_root_analysis)

        # add an observable to an old copy of the root
        observable = old_root.add_observable("test", "test_2")
        await system.process_analysis_request(old_root.create_analysis_request())

    # it should have still worked
    assert (await system.get_root_analysis(root)).get_observable(observable)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_process_duplicate_root_analysis_request(system):
    amt = AnalysisModuleType(name=ANALYSIS_TYPE_TEST, description="blah", cache_ttl=60)
    assert await system.register_analysis_module_type(amt) == amt

    root = system.new_root()
    test_observable = root.add_observable("test", "test")

    root_request = root.create_analysis_request()
    await system.process_analysis_request(root_request)

    # we should have a single work entry in the work queue
    assert await system.get_queue_size(amt) == 1

    # make the exact same request again
    root_request = root.create_analysis_request()
    await system.process_analysis_request(root_request)

    # should still only have one request
    assert await system.get_queue_size(amt) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cache_ttl",
    [
        (None),
        (60),
    ],
)
@pytest.mark.integration
async def test_process_duplicate_observable_analysis_request(cache_ttl, system):
    amt = AnalysisModuleType(name=ANALYSIS_TYPE_TEST, description="blah", cache_ttl=cache_ttl)
    assert await system.register_analysis_module_type(amt) == amt

    original_root = system.new_root()
    test_observable = original_root.add_observable("test", "test")

    original_request = original_root.create_analysis_request()
    await system.process_analysis_request(original_request)

    # we should have a single work entry in the work queue
    assert await system.get_queue_size(amt) == 1

    # make another request for the same observable but from a different root analysis
    root = system.new_root()
    test_observable = root.add_observable("test", "test")
    root_request = root.create_analysis_request()
    await system.process_analysis_request(root_request)

    if cache_ttl is not None:
        # there should still only be one outbound request
        assert await system.get_queue_size(amt) == 1

        # the first analysis request should now be linked to a new analysis request
        request = await system.get_next_analysis_request(OWNER_UUID, amt, 0)
        assert await system.get_linked_analysis_requests(request)

        # process the result of the original request
        request.initialize_result()
        request.modified_observable.add_analysis(type=amt, details={"Hello": "World"})
        await system.process_analysis_request(request)

        # now the second root analysis should have it's analysis completed
        root = await system.get_root_analysis(root.uuid)
        analysis = root.get_observable(test_observable).get_analysis(amt)
        assert analysis is not None
        assert analysis.root == root
        assert analysis.observable == request.observable
        assert await analysis.get_details() == await request.modified_observable.get_analysis(amt).get_details()

    else:
        # otherwise there should just be two requests
        assert await system.get_queue_size(amt) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cache_ttl",
    [
        (None),
        (60),
    ],
)
@pytest.mark.integration
async def test_process_analysis_result(cache_ttl, system):
    amt = AnalysisModuleType(ANALYSIS_TYPE_TEST, "blah", cache_ttl=cache_ttl)
    assert await system.register_analysis_module_type(amt) == amt

    root = system.new_root()
    test_observable = root.add_observable("test", "test")

    root_request = root.create_analysis_request()
    await system.process_analysis_request(root_request)

    # get the analysis request
    request = await system.get_next_analysis_request(OWNER_UUID, amt, 0)
    assert isinstance(request, AnalysisRequest)
    assert request.observable == test_observable
    assert request.type == amt
    assert request.root.uuid == root.uuid and request.root.version is not None
    assert request.status == TRACKING_STATUS_ANALYZING
    assert request.owner == OWNER_UUID

    request.initialize_result()
    request.modified_observable.add_analysis(type=amt, details={"Hello": "World"})
    await system.process_analysis_request(request)

    if cache_ttl is not None:
        # this analysis result for this observable should be cached now
        assert await system.get_cached_analysis_result(request.observable, request.type) is not None

    # get the root analysis and ensure this observable has the analysis now
    root = await system.get_root_analysis(root.uuid)
    assert root is not None
    observable = root.get_observable(request.observable)
    assert observable is not None
    analysis = observable.get_analysis(request.type)
    assert analysis is not None
    assert analysis.root == root
    assert analysis.observable == request.observable
    assert await analysis.get_details() == await request.modified_observable.get_analysis(amt).get_details()

    # request should be deleted
    assert await system.get_analysis_request(request.id) is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_process_analysis_result_modified_root(monkeypatch, system):
    """Test handling of processing root that is modified during processing."""
    amt = AnalysisModuleType("test", "")
    assert await system.register_analysis_module_type(amt) == amt

    root = system.new_root()
    test_observable = root.add_observable("test", "test")

    root_request = root.create_analysis_request()
    await system.process_analysis_request(root_request)

    # get the analysis request
    request = await system.get_next_analysis_request("test", amt, 0)
    request.initialize_result()
    request.modified_observable.add_analysis(type=amt, details={"Hello": "World"})

    original_get_root_analysis = system.get_root_analysis
    trigger = False

    async def hacked_get_root_analysis(_root):
        nonlocal root
        nonlocal original_get_root_analysis
        nonlocal trigger

        result = await original_get_root_analysis(_root)
        if trigger:
            return result

        # only do this once
        trigger = True

        if isinstance(_root, RootAnalysis):
            _root = _root.uuid

        root = await system.get_root_analysis(_root)
        await root.save()

        return result

    with monkeypatch.context() as m:
        m.setattr(system, "get_root_analysis", hacked_get_root_analysis)
        await system.process_analysis_request(request)

    # get the root analysis and ensure this observable has the analysis now
    root = await system.get_root_analysis(root.uuid)
    assert root is not None
    observable = root.get_observable(request.observable)
    assert observable is not None
    analysis = observable.get_analysis(request.type)
    assert analysis is not None
    assert analysis.root == root
    assert analysis.observable == request.observable
    assert await analysis.get_details() == await request.modified_observable.get_analysis(amt).get_details()

    # request should be deleted
    assert await system.get_analysis_request(request.id) is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_cached_analysis_result(system):
    amt = AnalysisModuleType(ANALYSIS_TYPE_TEST, "blah", cache_ttl=60)
    assert await system.register_analysis_module_type(amt) == amt

    root = system.new_root()
    test_observable = root.add_observable("test", "test")

    root_request = root.create_analysis_request()
    await system.process_analysis_request(root_request)

    # we should have a single work entry in the work queue
    assert await system.get_queue_size(amt) == 1

    # request should be deleted
    assert await system.get_analysis_request(root_request.id) is None

    request = await system.get_next_analysis_request(OWNER_UUID, amt, 0)
    request.initialize_result()
    request.modified_observable.add_analysis(type=amt, details={"Hello": "World"})
    await system.process_analysis_request(AnalysisRequest.from_dict(request.to_dict(), system))

    # this analysis result for this observable should be cached now
    assert await system.get_cached_analysis_result(request.observable, request.type) is not None

    # request should be deleted
    assert await system.get_analysis_request(request.id) is None

    # work queue should be empty
    assert await system.get_queue_size(amt) == 0

    # make another request for the same observable
    root = system.new_root()
    test_observable = root.add_observable("test", "test")

    root_request = root.create_analysis_request()
    await system.process_analysis_request(root_request)

    # request should be deleted
    assert await system.get_analysis_request(root_request.id) is None

    # work queue should be empty since the result was pulled from cache
    assert await system.get_queue_size(amt) == 0

    # get the root analysis and ensure this observable has the analysis now
    root = await system.get_root_analysis(root.uuid)
    assert root is not None
    observable = root.get_observable(request.observable)
    assert observable is not None
    analysis = observable.get_analysis(request.type)
    assert analysis is not None
    assert analysis.root == root
    assert analysis.observable == request.observable
    assert await analysis.get_details() == await request.modified_observable.get_analysis(amt).get_details()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_process_existing_analysis_merge(system):
    # register two different analysis modules
    amt_1 = AnalysisModuleType("test_1", "")
    await system.register_analysis_module_type(amt_1)

    amt_2 = AnalysisModuleType("test_2", "")
    await system.register_analysis_module_type(amt_2)

    root = system.new_root()
    test_observable = root.add_observable("test", "test")
    await root.submit()

    # act like these two modules are running at the same time
    request_1 = await system.get_next_analysis_request(OWNER_UUID, amt_1, 0)
    request_2 = await system.get_next_analysis_request(OWNER_UUID, amt_2, 0)

    # process the first one
    request_1.initialize_result()
    request_1.modified_observable.add_tag("tag_1")  # make a modification to the observable
    analysis = request_1.modified_observable.add_analysis(type=amt_1)
    await system.process_analysis_request(request_1)

    # process the second one
    request_2.initialize_result()
    analysis = request_2.modified_observable.add_analysis(type=amt_2)
    await system.process_analysis_request(request_2)

    root = await system.get_root_analysis(root)
    test_observable = root.get_observable(test_observable)
    assert test_observable.has_tag("tag_1")
    assert test_observable.get_analysis(amt_1)
    assert test_observable.get_analysis(amt_2)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_unknown_dependency(system):
    # amt_dep depends on amt which has not registered yet
    amt_dep = AnalysisModuleType(ANALYSIS_TYPE_TEST_DEP, "test", dependencies=[ANALYSIS_TYPE_TEST])
    with pytest.raises(AnalysisModuleTypeDependencyError):
        assert await system.register_analysis_module_type(amt_dep)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_known_dependency(system):
    amt = AnalysisModuleType(ANALYSIS_TYPE_TEST, "test")
    assert await system.register_analysis_module_type(amt) == amt

    # amt_dep depends on amt
    amt_dep = AnalysisModuleType(ANALYSIS_TYPE_TEST_DEP, "test", dependencies=[ANALYSIS_TYPE_TEST])
    assert await system.register_analysis_module_type(amt_dep)

    root = system.new_root()
    test_observable = root.add_observable("test", "test")

    root_request = root.create_analysis_request()
    await system.process_analysis_request(root_request)

    # this should have one entry
    assert await system.get_queue_size(amt) == 1

    # but not this one (yet) due to the dependency
    assert await system.get_queue_size(amt_dep) == 0

    # process the amt request
    request = await system.get_next_analysis_request(OWNER_UUID, amt, 0)
    request.initialize_result()
    request.modified_observable.add_analysis(type=amt, details={"Hello": "World"})
    await system.process_analysis_request(request)

    # now we should have a request for the dependency
    assert await system.get_queue_size(amt_dep) == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_chained_dependency(system):
    amt_1 = AnalysisModuleType("test_1", "")
    assert await system.register_analysis_module_type(amt_1)

    # amt_2 depends on amt_1
    amt_2 = AnalysisModuleType("test_2", "", dependencies=["test_1"])
    assert await system.register_analysis_module_type(amt_2)

    # amt_3 depends on amt_2
    amt_3 = AnalysisModuleType("test_3", "", dependencies=["test_2"])
    assert await system.register_analysis_module_type(amt_3)

    root = system.new_root()
    test_observable = root.add_observable("test", "test")

    root_request = root.create_analysis_request()
    await system.process_analysis_request(root_request)

    # this should have one entry for amt_1
    assert await system.get_queue_size(amt_1) == 1

    # but not this one the others
    assert await system.get_queue_size(amt_2) == 0
    assert await system.get_queue_size(amt_3) == 0

    # process the amt request
    request = await system.get_next_analysis_request(OWNER_UUID, amt_1, 0)
    request.initialize_result()
    request.modified_observable.add_analysis(type=amt_1, details={"Hello": "World"})
    await system.process_analysis_request(request)

    # now amt_2 should be ready but still not amt_3
    assert await system.get_queue_size(amt_1) == 0
    assert await system.get_queue_size(amt_2) == 1
    assert await system.get_queue_size(amt_3) == 0

    # process the amt request
    request = await system.get_next_analysis_request(OWNER_UUID, amt_2, 0)
    request.initialize_result()
    request.modified_observable.add_analysis(type=amt_2, details={"Hello": "World"})
    await system.process_analysis_request(request)

    # now amt_3 should be ready
    assert await system.get_queue_size(amt_1) == 0
    assert await system.get_queue_size(amt_2) == 0
    assert await system.get_queue_size(amt_3) == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_circ_dependency(system):
    amt_1 = AnalysisModuleType("test_1", "")
    assert await system.register_analysis_module_type(amt_1)

    # amt_2 depends on amt_1
    amt_2 = AnalysisModuleType("test_2", "", dependencies=["test_1"])
    assert await system.register_analysis_module_type(amt_2)

    # and now amt_1 depends on amt_2
    amt_1 = AnalysisModuleType("test_1", "", dependencies=["test_2"])
    with pytest.raises(CircularDependencyError):
        assert await system.register_analysis_module_type(amt_1)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_self_dependency(system):
    # depending on amt when amt isn' registered yet
    amt_1 = AnalysisModuleType("test_1", "", dependencies=["test_1"])
    with pytest.raises(AnalysisModuleTypeDependencyError):
        assert await system.register_analysis_module_type(amt_1)

    # define it
    amt_1 = AnalysisModuleType("test_1", "")
    assert await system.register_analysis_module_type(amt_1)

    # redefine to depend on yourself
    # cannot depend on yourself! (low self esteem error)
    amt_1 = AnalysisModuleType("test_1", "", dependencies=["test_1"])
    with pytest.raises(CircularDependencyError):
        assert await system.register_analysis_module_type(amt_1)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_cancel_analysis_from_result(system):
    amt = AnalysisModuleType("test", "")
    await system.register_analysis_module_type(amt)

    root = system.new_root()
    observable = root.add_observable("test", "test")

    request = root.create_analysis_request()
    await system.process_analysis_request(request)

    # get the analysis request
    request = await system.get_next_analysis_request(OWNER_UUID, amt, 0)
    request.initialize_result()
    analysis = request.modified_observable.add_analysis(type=amt, details={"Hello": "World"})
    new_observable = analysis.add_observable("new", "new")
    request.result.cancel_analysis("test")
    await system.process_analysis_request(request)

    # root analysis should be cancelled
    root = await system.get_root_analysis(root.uuid)
    assert root.analysis_cancelled
    assert root.analysis_cancelled_reason == "test"

    # we should still have the analysis and the new observable we added in that result
    observable = root.get_observable(observable)
    analysis = observable.get_analysis(amt)
    assert analysis is not None
    new_observable = root.get_observable(new_observable)
    assert new_observable is not None

    # we should not have any new work requests since the analysis was cancelled
    assert await system.get_queue_size(amt) == 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_cancel_analysis(system):
    amt = AnalysisModuleType("test", "")
    await system.register_analysis_module_type(amt)

    root = system.new_root()
    observable = root.add_observable("test", "test")

    request = root.create_analysis_request()
    await system.process_analysis_request(request)

    # before we work the queue we update the root to cancel analysis
    root = await system.get_root_analysis(root)
    root.cancel_analysis("test")
    await system.process_analysis_request(root.create_analysis_request())

    root = await system.get_root_analysis(root)
    assert root.analysis_cancelled
    assert root.analysis_cancelled_reason == "test"

    # now work the queue
    request = await system.get_next_analysis_request(OWNER_UUID, amt, 0)
    # now it doesn't say it's cancelled here because this was created before we cancelled it
    assert not request.root.analysis_cancelled
    # post our results
    request.initialize_result()
    analysis = request.modified_observable.add_analysis(type=amt, details={"Hello": "World"})
    new_observable = analysis.add_observable("new", "new")
    request.result.cancel_analysis("test")
    await system.process_analysis_request(request)

    # root analysis should be cancelled here since this a fresh request
    root = await system.get_root_analysis(root.uuid)
    assert root.analysis_cancelled
    assert root.analysis_cancelled_reason == "test"

    # we should still have the analysis and the new observable we added in that result
    observable = root.get_observable(observable)
    analysis = observable.get_analysis(amt)
    assert analysis is not None
    new_observable = root.get_observable(new_observable)
    assert new_observable is not None

    # we should not have any new work requests since the analysis was cancelled
    assert await system.get_queue_size(amt) == 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_analyze_canceled_analysis(system):
    amt = AnalysisModuleType("test", "")
    await system.register_analysis_module_type(amt)

    root = system.new_root()
    observable = root.add_observable("test", "test")

    request = root.create_analysis_request()
    await system.process_analysis_request(request)

    # before we work the queue we update the root to cancel analysis
    root = await system.get_root_analysis(root)
    root.cancel_analysis("test")
    await system.process_analysis_request(root.create_analysis_request())

    root = await system.get_root_analysis(root)
    assert root.analysis_cancelled
    assert root.analysis_cancelled_reason == "test"

    # now work the queue
    request = await system.get_next_analysis_request(OWNER_UUID, amt, 0)
    # now it doesn't say it's cancelled here because this was created before we cancelled it
    assert not request.root.analysis_cancelled
    # post our results
    request.initialize_result()
    analysis = request.modified_observable.add_analysis(type=amt, details={"Hello": "World"})
    request.result.cancel_analysis("test")
    await system.process_analysis_request(request)

    # root analysis should be cancelled here since this a fresh request
    root = await system.get_root_analysis(root.uuid)
    assert root.analysis_cancelled
    assert root.analysis_cancelled_reason == "test"

    # now resubmit the root with a new observable and the canceled flag reset
    root.analysis_cancelled = False
    root.analysis_cancelled_reason = None
    other_observable = root.add_observable("test", "other")
    await system.process_analysis_request(root.create_analysis_request())

    # we should have a request here even though this root was previously canceled
    request = await system.get_next_analysis_request(OWNER_UUID, amt, 0)
    assert not request.root.analysis_cancelled
    assert request.observable == other_observable


@pytest.mark.asyncio
@pytest.mark.integration
async def test_root_analysis_default_expiration(system):
    # by default a root should not expire
    root = system.new_root()
    assert not await root.is_expired()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_root_analysis_explicit_expiration(system):
    # but we can set that explicitly
    root = system.new_root(expires=True)
    assert await root.is_expired()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_root_analysis_expiration_detection_points(system):
    # but a root will not expire if it has a detection point
    root = system.new_root(expires=True)
    root.add_detection_point("test")
    assert not await root.is_expired()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_root_analysis_expiration_processing(system):
    # root analysis set to expire should be removed after it is processed
    root = system.new_root(expires=True)
    await root.submit()
    assert not await system.get_root_analysis(root.uuid)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_root_analysis_expiration_processing_detection_points(system):
    # but not if it has a detection point
    root = system.new_root(expires=True)
    root.add_detection_point("test")
    await root.submit()
    assert await system.get_root_analysis(root.uuid)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_root_analysis_expiration_processing_outstanding_requests(system):
    # and not if it has any outstanding analysis requests
    amt = await system.register_analysis_module_type(AnalysisModuleType("test", ""))
    root = system.new_root(expires=True)
    observable = root.add_observable("test", "test")
    await root.submit()
    assert await system.get_root_analysis(root.uuid)
    request = await system.get_next_analysis_request("test", amt, 0)
    # analysis requests have still not completed yet...
    assert await system.get_root_analysis(root.uuid)
    request.initialize_result()
    request.modified_observable.add_analysis(type=amt, details={"hello": "world"})
    await request.submit()
    # should be gone now because the analysis requests have completed
    assert not await system.get_root_analysis(root.uuid)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_root_analysis_expiration_processing_outstanding_root_dependency(system):
    # and then in this case we have one root that depends on the analysis of another root
    amt = await system.register_analysis_module_type(AnalysisModuleType(name="test", description="", cache_ttl=300))
    root = system.new_root(expires=True)
    observable = root.add_observable("test", "test")
    await root.submit()
    assert await system.get_root_analysis(root.uuid)
    root_2 = system.new_root(expires=True)
    observable_2 = root_2.add_observable("test", "test")
    await root_2.submit()
    # at this point root_2 has piggy-backed on root
    assert await system.get_root_analysis(root_2.uuid)
    # complete the first root
    request = await system.get_next_analysis_request("test", amt, 0)
    # analysis requests have still not completed yet...
    assert await system.get_root_analysis(root.uuid)
    assert await system.get_root_analysis(root_2.uuid)
    request.initialize_result()
    request.modified_observable.add_analysis(type=amt, details={"hello": "world"})
    await request.submit()
    # now they should both be gone because they were both set to expire
    assert not await system.get_root_analysis(root.uuid)
    assert not await system.get_root_analysis(root_2.uuid)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_manual_analysis_module_type(system):
    # analysis modules that have the manual flag set to True do not execute unless the
    # target observable has a directive with a value of manual:type_name
    # where type_name is the name of the analysis module type
    amt = await system.register_analysis_module_type(AnalysisModuleType(name="test", description="", manual=True))
    root = system.new_root()
    observable = root.add_observable("test", "test")
    await root.submit()

    # there should not be any analysis requests since the module is a manual type
    assert await system.get_queue_size(amt) == 0

    root = await system.get_root_analysis(root)
    # request manual analysis
    root.get_observable(observable).request_analysis(amt)
    await root.submit()

    # and now there should be 1 since added the required directive with the request_manual_analysis function
    assert await system.get_queue_size(amt) == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_expired_analysis_request_processing(system):
    amt = await system.register_analysis_module_type(
        AnalysisModuleType(name="test", description="", timeout=0, cache_ttl=600)
    )
    root = system.new_root()
    observable = root.add_observable("test", "test")
    await root.submit()

    request = await system.get_next_analysis_request("test", amt, 0)
    assert request

    # when we ask again we get the same request because it expired already
    assert await system.get_next_analysis_request("test", amt, 0) == request
