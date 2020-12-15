# vim: ts=4:sw=4:et:cc=120

import datetime

import pytest

from ace.analysis import RootAnalysis, Observable
from ace.constants import F_TEST

from ace.system.analysis_module import AnalysisModuleType
from ace.system.caching import generate_cache_key, cache_analysis_result, get_cached_analysis_result

amt_1 = AnalysisModuleType(name="test_1", description="test_1", cache_ttl=600)

amt_2 = AnalysisModuleType(name="test_2", description="test_2", cache_ttl=600)

amt_1_v2 = AnalysisModuleType(name="test_2", description="test_2", version="1.0.2", cache_ttl=600)

amt_no_cache = AnalysisModuleType(name="test_no_cache", description="test_no_cache2")

amt_fast_expire_cache = AnalysisModuleType(
    name="test_fast_expire_cache", description="test_fast_expire_cache", cache_ttl=0
)

amt_additional_cache_keys_1 = AnalysisModuleType(
    name="test_additional_cache_keys",
    description="test_additional_cache_keys",
    cache_ttl=600,
    additional_cache_keys=["yara_rules:v1.0.0"],
)

amt_additional_cache_keys_2 = AnalysisModuleType(
    name="test_additional_cache_keys",
    description="test_additional_cache_keys",
    cache_ttl=600,
    additional_cache_keys=["yara_rules:v1.0.1"],
)

amt_multiple_cache_keys_1 = AnalysisModuleType(
    name="test_multiple_cache_keys",
    description="test_multiple_cache_keys",
    cache_ttl=600,
    additional_cache_keys=["key_a", "key_b"],
)

amt_multiple_cache_keys_2 = AnalysisModuleType(
    name="test_multiple_cache_keys",
    description="test_multiple_cache_keys",
    cache_ttl=600,
    additional_cache_keys=["key_b", "key_a"],
)

TEST_1 = "test_1"
TEST_2 = "test_2"

observable_1 = Observable(F_TEST, TEST_1)
observable_2 = Observable(F_TEST, TEST_2)
observable_1_with_time = Observable(F_TEST, TEST_2, time=datetime.datetime.now())


@pytest.mark.unit
@pytest.mark.parametrize(
    "o_left, amt_left, o_right, amt_right, expected",
    [
        # same observable and amt
        (observable_1, amt_1, observable_1, amt_1, True),
        # different observable same amt
        (observable_1, amt_1, observable_2, amt_1, False),
        # same observable but with different times same amt
        (observable_1, amt_1, observable_1_with_time, amt_1, False),
        # same observable but with different amt
        (observable_1, amt_1, observable_1, amt_2, False),
        # same observable same amt but different amt version
        (observable_1, amt_1, observable_1, amt_1_v2, False),
        # same observable same amt same additional cache keys
        (observable_1, amt_additional_cache_keys_1, observable_1, amt_additional_cache_keys_1, True),
        # same observable same amt different additional cache keys
        (observable_1, amt_additional_cache_keys_1, observable_1, amt_additional_cache_keys_2, False),
        # order of cache keys should not matter
        (observable_1, amt_multiple_cache_keys_1, observable_1, amt_multiple_cache_keys_2, True),
    ],
)
def test_generate_cache_key(o_left, amt_left, o_right, amt_right, expected):
    assert (generate_cache_key(o_left, amt_left) == generate_cache_key(o_right, amt_right)) == expected


@pytest.mark.unit
def test_generate_cache_key_no_cache():
    # if the cache_ttl is 0 (the default) then this function returns a 0
    assert generate_cache_key(observable_1, amt_no_cache) is None


@pytest.mark.unit
@pytest.mark.parametrize(
    "observable, amt",
    [
        (observable_1, None),
        (None, amt_1),
        (None, None),
    ],
)
def test_generate_cache_invalid_parameters(observable, amt):
    assert generate_cache_key(observable, amt) is None


@pytest.mark.integration
def test_cache_analysis_result():
    root = RootAnalysis()
    observable = root.add_observable("type", "value")
    request = observable.create_analysis_request(amt_1)
    request.result = request.create_result()
    analysis = request.result.observable.add_analysis(type=amt_1)

    assert cache_analysis_result(request) is not None
    assert get_cached_analysis_result(observable, amt_1) == request


@pytest.mark.integration
def test_nocache_analysis():
    root = RootAnalysis()
    observable = root.add_observable("type", "value")
    request = observable.create_analysis_request(amt_no_cache)
    request.result = request.create_result()
    analysis = request.result.observable.add_analysis(type=amt_no_cache)

    assert cache_analysis_result(request) is None
    assert get_cached_analysis_result(observable, amt_no_cache) is None


@pytest.mark.integration
def test_cache_expiration():
    root = RootAnalysis()
    observable = root.add_observable("type", "value")
    request = observable.create_analysis_request(amt_fast_expire_cache)
    request.result = request.create_result()
    analysis = request.result.observable.add_analysis(type=amt_fast_expire_cache)

    assert cache_analysis_result(request) is not None
    # should have expired right away
    assert get_cached_analysis_result(observable, amt_fast_expire_cache) is None
