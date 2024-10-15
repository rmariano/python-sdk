import json
import os
import time
import unittest
from unittest.mock import patch

from network_stub import NetworkStub
from statsig import StatsigOptions, statsig, StatsigUser
from statsig.evaluation_details import EvaluationDetails, EvaluationReason
from statsig.statsig_options import DataSource

_network_stub = NetworkStub("http://test-sync-config-fallback", mock_statsig_api=True)
with open(os.path.join(os.path.abspath(os.path.dirname(__file__)), '../testdata/download_config_specs.json')) as r:
    CONFIG_SPECS_RESPONSE = r.read()
PARSED_CONFIG_SPEC = json.loads(CONFIG_SPECS_RESPONSE)

UPDATED_TIME_CONFIG_SPEC = PARSED_CONFIG_SPEC.copy()
UPDATED_TIME_CONFIG_SPEC['time'] = 1631638014821


@patch('requests.request', side_effect=_network_stub.mock)
class TestSyncConfigFallback(unittest.TestCase):
    @classmethod
    @patch('requests.request', side_effect=_network_stub.mock)
    def setUpClass(cls, mock_proxy):
        cls.dcs_called = False
        cls.statsig_dcs_called = False
        cls.status_code = 200

        cls.test_user = StatsigUser("123", email="testuser@statsig.com")

    def setUp(self):
        self.__class__.dcs_called = False
        self.__class__.statsig_dcs_called = False
        self.__class__.status_code = 200

        def common_callback(url, **kwargs):
            if 'statsig' in url.netloc:
                self.__class__.statsig_dcs_called = True
                return PARSED_CONFIG_SPEC
            else:
                self.__class__.dcs_called = True

            if self.__class__.status_code == 200:
                return PARSED_CONFIG_SPEC
            if self.__class__.status_code == 300:
                return "{jiBbRIsh;"
            if self.__class__.status_code == 400:
                return "Bad Request"
            if self.__class__.status_code == 500:
                raise Exception("Internal Server Error")

        _network_stub.stub_request_with_function(
            "download_config_specs/.*", self.__class__.status_code, common_callback)
        _network_stub.stub_statsig_api_request_with_function(
            "download_config_specs/.*", 200, common_callback)

    def tearDown(self):
        statsig.shutdown()
        _network_stub.reset()

    def test_default_sync_success(self, request_mock):
        options = StatsigOptions(api=_network_stub.host, fallback_to_statsig_api=True, rulesets_sync_interval=1)
        statsig.initialize("secret-key", options)
        gate = statsig.get_feature_gate(self.test_user, "always_on_gate")
        eval_detail: EvaluationDetails = gate.get_evaluation_details()
        self.assertEqual(eval_detail.reason, EvaluationReason.network)
        self.assertEqual(eval_detail.config_sync_time, 1631638014811)
        time.sleep(1.1)
        self.assertFalse(self.__class__.statsig_dcs_called)

    def test_fallback_when_out_of_sync(self, request_mock):
        options = StatsigOptions(api_for_download_config_specs=_network_stub.host, fallback_to_statsig_api=True,
                                 rulesets_sync_interval=1, out_of_sync_threshold_in_s=0.5)
        statsig.initialize("secret-key", options)
        gate = statsig.get_feature_gate(self.test_user, "always_on_gate")
        eval_detail: EvaluationDetails = gate.get_evaluation_details()
        self.assertEqual(eval_detail.reason, EvaluationReason.network)
        self.assertEqual(eval_detail.config_sync_time, 1631638014811)
        time.sleep(1.1)
        self.assertTrue(self.__class__.statsig_dcs_called)

    def test_no_fallback_when_not_out_of_sync(self, request_mock):
        options = StatsigOptions(api_for_download_config_specs=_network_stub.host, fallback_to_statsig_api=True,
                                 rulesets_sync_interval=1, out_of_sync_threshold_in_s=4e10)
        statsig.initialize("secret-key", options)
        gate = statsig.get_feature_gate(self.test_user, "always_on_gate")
        eval_detail: EvaluationDetails = gate.get_evaluation_details()
        self.assertEqual(eval_detail.reason, EvaluationReason.network)
        self.assertEqual(eval_detail.config_sync_time, 1631638014811)
        time.sleep(1.1)
        self.assertFalse(self.__class__.statsig_dcs_called)

    def test_fallback_when_dcs_400(self, request_mock):
        self.__class__.status_code = 400
        options = StatsigOptions(api_for_download_config_specs=_network_stub.host, fallback_to_statsig_api=True,
                                 rulesets_sync_interval=1)
        statsig.initialize("secret-key", options)
        self.assertEqual(statsig.get_instance()._spec_store.init_source, DataSource.STATSIG_NETWORK)
        self.get_gate_and_validate()
        self.wait_for_sync_and_validate()

    def test_fallback_when_dcs_500(self, request_mock):
        self.__class__.status_code = 500
        options = StatsigOptions(api_for_download_config_specs=_network_stub.host, fallback_to_statsig_api=True,
                                 rulesets_sync_interval=1)
        statsig.initialize("secret-key", options)
        self.assertEqual(statsig.get_instance()._spec_store.init_source, DataSource.STATSIG_NETWORK)
        self.get_gate_and_validate()
        self.wait_for_sync_and_validate()

    def test_fallback_when_dcs_invalid_json(self, request_mock):
        self.__class__.status_code = 300
        options = StatsigOptions(api_for_download_config_specs=_network_stub.host, fallback_to_statsig_api=True,
                                 rulesets_sync_interval=1)
        statsig.initialize("secret-key", options)
        self.assertEqual(statsig.get_instance()._spec_store.init_source, DataSource.STATSIG_NETWORK)
        self.get_gate_and_validate()
        self.wait_for_sync_and_validate()

    def test_fallback_when_invalid_gzip_content(self, request_mock):
        def cb(url, **kwargs):
            self.__class__.dcs_called = True
            return "{jiBbRIsh;"

        _network_stub.stub_request_with_function(
            "download_config_specs/.*", 200, cb,
            headers={"Content-Encoding": "gzip"}
        )
        options = StatsigOptions(api_for_download_config_specs=_network_stub.host, fallback_to_statsig_api=True,
                                 rulesets_sync_interval=1)
        statsig.initialize("secret-key", options)
        self.assertEqual(statsig.get_instance()._spec_store.init_source, DataSource.STATSIG_NETWORK)
        self.get_gate_and_validate()
        self.wait_for_sync_and_validate()

    def wait_for_sync_and_validate(self):
        _network_stub.stub_statsig_api_request_with_value("download_config_specs/.*", 200,
                                                          UPDATED_TIME_CONFIG_SPEC)
        time.sleep(1.1)
        gate = statsig.get_feature_gate(self.test_user, "always_on_gate")
        eval_detail: EvaluationDetails = gate.get_evaluation_details()
        self.assertEqual(eval_detail.config_sync_time, 1631638014821)

    def get_gate_and_validate(self):
        gate = statsig.get_feature_gate(self.test_user, "always_on_gate")
        eval_detail: EvaluationDetails = gate.get_evaluation_details()
        self.assertEqual(eval_detail.reason, EvaluationReason.network)
        self.assertEqual(eval_detail.config_sync_time, 1631638014811)
        self.assertTrue(self.__class__.dcs_called)
        self.assertTrue(self.__class__.statsig_dcs_called)