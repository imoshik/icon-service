# -*- coding: utf-8 -*-

# Copyright 2017-2018 theloop Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""IconScoreEngine testcase
"""

import asyncio
import os
import unittest
from typing import TYPE_CHECKING

import time

from iconcommons.icon_config import IconConfig
from iconservice import ExceptionCode
from iconservice.base.address import AddressPrefix, ZERO_SCORE_ADDRESS
from iconservice.icon_config import default_icon_config
from iconservice.icon_constant import ConfigKey
from iconservice.icon_inner_service import IconScoreInnerTask
from tests import create_block_hash, create_address, create_tx_hash, rmtree, raise_exception_start_tag, \
    raise_exception_end_tag
from tests.in_memory_zip import InMemoryZip

if TYPE_CHECKING:
    from iconservice.base.address import Address


class TestIntegrateFallbackCall(unittest.TestCase):
    asnyc_loop_array = []

    def setUp(self):
        self._state_db_root_path = '.statedb'
        self._score_root_path = '.score'

        rmtree(self._score_root_path)
        rmtree(self._state_db_root_path)

        self._block_height = 0
        self._prev_block_hash = None
        self._version = 3
        self._step_limit = 4 * 10 ** 6

        self._admin_addr = create_address(AddressPrefix.EOA, b'ADMIN')
        conf = IconConfig("", default_icon_config)
        conf.load()
        conf.update_conf({ConfigKey.BUILTIN_SCORE_OWNER: str(self._admin_addr)})

        self._inner_task = IconScoreInnerTask(conf)
        self._inner_task._open()

        self._genesis_addr = create_address(AddressPrefix.EOA, b'genesis')

        is_commit, tx_results = self._run_async(self._genesis_invoke())
        self.assertEqual(is_commit, True)
        self.assertEqual(tx_results[0]['status'], hex(1))

    def tearDown(self):
        self._inner_task._close()
        rmtree(self._score_root_path)
        rmtree(self._state_db_root_path)

        for loop in self.asnyc_loop_array:
            loop.close()
        self.asnyc_loop_array.clear()

    @classmethod
    def _run_async(cls, asnyc_func):
        loop = asyncio.new_event_loop()
        cls.asnyc_loop_array.append(loop)
        return loop.run_until_complete(asnyc_func)

    async def _genesis_invoke(self) -> tuple:
        tx_hash = create_tx_hash(b'genesis')
        timestamp_us = int(time.time() * 10 ** 6)
        version = 3
        request_params = {
            'txHash': bytes.hex(tx_hash),
            'version': hex(version),
            'timestamp': hex(timestamp_us)
        }

        tx = {
            'method': 'icx_sendTransaction',
            'params': request_params,
            'genesisData': {
                "accounts": [
                    {
                        "name": "genesis",
                        "address": str(self._genesis_addr),
                        "balance": hex(100 * 10 ** 18)
                    },
                    {
                        "name": "fee_treasury",
                        "address": "hx1000000000000000000000000000000000000000",
                        "balance": hex(0)
                    }
                ]
            },
        }

        make_request = {'transactions': [tx]}
        block_height: int = 0
        block_hash = create_block_hash()

        make_request['block'] = {
            'blockHeight': hex(block_height),
            'blockHash': bytes.hex(block_hash),
            'timestamp': hex(timestamp_us)
        }

        precommit_request = {'blockHeight': hex(block_height),
                             'blockHash': bytes.hex(block_hash)}

        invoke_response = await self._inner_task.invoke(make_request)
        tx_results = invoke_response.get('txResults')
        is_commit = False
        if not isinstance(tx_results, dict):
            await self._inner_task.remove_precommit_state(precommit_request)
        elif tx_results[bytes.hex(tx_hash)]['status'] == hex(1):
            is_commit = True
            await self._inner_task.write_precommit_state(precommit_request)
            self._block_height += 1
            self._prev_block_hash = bytes.hex(block_hash)
        else:
            await self._inner_task.remove_precommit_state(precommit_request)

        if tx_results is None:
            return is_commit, invoke_response
        else:
            return is_commit, list(tx_results.values())

    async def _deploy_zip(self, zip_name: str, to_addr: 'Address', from_addr: 'Address', params=None):
        if params is None:
            params = {}

        root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../'))
        path = os.path.join(root_path, f'tests/sample/test_fallback_call_scores/{zip_name}')
        mz = InMemoryZip()
        mz.zip_in_memory(path)
        data = f'0x{mz.data.hex()}'

        install_data = {'contentType': 'application/zip', 'content': data, 'params': params}

        timestamp_us = int(time.time() * 10 ** 6)
        nonce = 0
        signature = "VAia7YZ2Ji6igKWzjR2YsGa2m53nKPrfK7uXYW78QLE+ATehAVZPC40szvAiA6NEU5gCYB4c4qaQzqDh2ugcHgA="

        request_params = {
            "version": hex(self._version),
            "from": str(from_addr),
            "to": str(to_addr),
            "stepLimit": hex(self._step_limit),
            "timestamp": hex(timestamp_us),
            "nonce": hex(nonce),
            "signature": signature,
            "dataType": "deploy",
            "data": install_data
        }

        method = 'icx_sendTransaction'
        # Insert txHash into request params
        tx_hash = create_tx_hash()
        request_params['txHash'] = bytes.hex(tx_hash)
        tx = {
            'method': method,
            'params': request_params
        }

        response = await self._inner_task.validate_transaction(tx)

        make_request = {'transactions': [tx]}
        block_height: int = self._block_height
        block_hash = create_block_hash()

        make_request['block'] = {
            'blockHeight': hex(block_height),
            'blockHash': bytes.hex(block_hash),
            'timestamp': hex(timestamp_us),
            'prevBlockHash': self._prev_block_hash
        }

        precommit_request = {'blockHeight': hex(block_height),
                             'blockHash': bytes.hex(block_hash)}

        invoke_response = await self._inner_task.invoke(make_request)
        tx_results = invoke_response.get('txResults')
        is_commit = False
        if not isinstance(tx_results, dict):
            await self._inner_task.remove_precommit_state(precommit_request)
        elif tx_results[bytes.hex(tx_hash)]['status'] == hex(1):
            is_commit = True
            await self._inner_task.write_precommit_state(precommit_request)
            self._block_height += 1
            self._prev_block_hash = bytes.hex(block_hash)
        else:
            await self._inner_task.remove_precommit_state(precommit_request)

        if tx_results is None:
            return is_commit, invoke_response
        else:
            return is_commit, list(tx_results.values())

    async def _call_method_score(self,
                                 addr_from: 'Address',
                                 addr_to: str,
                                 method: str,
                                 params: dict):

        timestamp_us = int(time.time() * 10 ** 6)
        nonce = 0
        signature = "VAia7YZ2Ji6igKWzjR2YsGa2m53nKPrfK7uXYW78QLE+ATehAVZPC40szvAiA6NEU5gCYB4c4qaQzqDh2ugcHgA="

        request_params = {
            "version": hex(self._version),
            "from": str(addr_from),
            "to": addr_to,
            "value": hex(0),
            "stepLimit": hex(self._step_limit),
            "timestamp": hex(timestamp_us),
            "nonce": hex(nonce),
            "signature": signature,
            "dataType": "call",
            "data": {
                "method": method,
                "params": params
            }
        }

        method = 'icx_sendTransaction'
        # Insert txHash into request params
        tx_hash = create_tx_hash()
        request_params['txHash'] = bytes.hex(tx_hash)
        tx = {
            'method': method,
            'params': request_params
        }

        response = await self._inner_task.validate_transaction(tx)
        self.assertEqual(response, hex(0))

        make_request = {'transactions': [tx]}
        block_height: int = self._block_height
        block_hash = create_block_hash()

        make_request['block'] = {
            'blockHeight': hex(block_height),
            'blockHash': bytes.hex(block_hash),
            'timestamp': hex(timestamp_us),
            'prevBlockHash': self._prev_block_hash
        }

        precommit_request = {'blockHeight': hex(block_height),
                             'blockHash': bytes.hex(block_hash)}

        invoke_response = await self._inner_task.invoke(make_request)
        tx_results = invoke_response.get('txResults')
        is_commit = False
        if not isinstance(tx_results, dict):
            await self._inner_task.remove_precommit_state(precommit_request)
        elif tx_results[bytes.hex(tx_hash)]['status'] == hex(1):
            is_commit = True
            await self._inner_task.write_precommit_state(precommit_request)
            self._block_height += 1
            self._prev_block_hash = bytes.hex(block_hash)
        else:
            await self._inner_task.remove_precommit_state(precommit_request)

        if tx_results is None:
            return is_commit, invoke_response
        else:
            return is_commit, list(tx_results.values())

    async def _call_method_score2(self,
                                  addr_from: 'Address',
                                  addr_to: str,
                                  method1: str,
                                  params1: dict,
                                  method2: str,
                                  params2: dict):

        timestamp_us = int(time.time() * 10 ** 6)
        nonce = 0
        signature = "VAia7YZ2Ji6igKWzjR2YsGa2m53nKPrfK7uXYW78QLE+ATehAVZPC40szvAiA6NEU5gCYB4c4qaQzqDh2ugcHgA="

        request_params1 = {
            "version": hex(self._version),
            "from": str(addr_from),
            "to": addr_to,
            "value": hex(0),
            "stepLimit": hex(self._step_limit),
            "timestamp": hex(timestamp_us),
            "nonce": hex(nonce),
            "signature": signature,
            "dataType": "call",
            "data": {
                "method": method1,
                "params": params1
            }
        }

        request_params2 = {
            "version": hex(self._version),
            "from": str(addr_from),
            "to": addr_to,
            "value": hex(0),
            "stepLimit": hex(self._step_limit),
            "timestamp": hex(timestamp_us),
            "nonce": hex(nonce),
            "signature": signature,
            "dataType": "call",
            "data": {
                "method": method2,
                "params": params2
            }
        }

        method = 'icx_sendTransaction'
        # Insert txHash into request params
        tx_hash1 = create_tx_hash()
        request_params1['txHash'] = bytes.hex(tx_hash1)
        tx1 = {
            'method': method,
            'params': request_params1
        }
        response = await self._inner_task.validate_transaction(tx1)
        self.assertEqual(response, hex(0))

        tx_hash2 = create_tx_hash()
        request_params2['txHash'] = bytes.hex(tx_hash2)
        tx2 = {
            'method': method,
            'params': request_params2
        }
        response = await self._inner_task.validate_transaction(tx2)
        self.assertEqual(response, hex(0))

        make_request = {'transactions': [tx1, tx2]}
        block_height: int = self._block_height
        block_hash = create_block_hash()

        make_request['block'] = {
            'blockHeight': hex(block_height),
            'blockHash': bytes.hex(block_hash),
            'timestamp': hex(timestamp_us),
            'prevBlockHash': self._prev_block_hash
        }

        precommit_request = {'blockHeight': hex(block_height),
                             'blockHash': bytes.hex(block_hash)}

        invoke_response = await self._inner_task.invoke(make_request)
        tx_results = invoke_response.get('txResults')
        is_commit = False
        if not isinstance(tx_results, dict):
            await self._inner_task.remove_precommit_state(precommit_request)
        elif tx_results[bytes.hex(tx_hash2)]['status'] == hex(1):
            is_commit = True
            await self._inner_task.write_precommit_state(precommit_request)
            self._block_height += 1
            self._prev_block_hash = bytes.hex(block_hash)
        else:
            await self._inner_task.remove_precommit_state(precommit_request)

        if tx_results is None:
            return is_commit, invoke_response
        else:
            return is_commit, list(tx_results.values())

    async def _send_icx_invoke(self,
                               addr_from: 'Address',
                               addr_to: 'Address',
                               value: int):

        timestamp_us = int(time.time() * 10 ** 6)
        nonce = 1
        signature = "VAia7YZ2Ji6igKWzjR2YsGa2m53nKPrfK7uXYW78QLE+ATehAVZPC40szvAiA6NEU5gCYB4c4qaQzqDh2ugcHgA="

        request_params = {
            "version": hex(self._version),
            "from": str(addr_from),
            "to": str(addr_to),
            "value": hex(value),
            "stepLimit": hex(self._step_limit),
            "timestamp": hex(timestamp_us),
            "nonce": hex(nonce),
            "signature": signature
        }

        method = 'icx_sendTransaction'
        # Insert txHash into request params
        tx_hash = create_tx_hash(b'txHash1')
        request_params['txHash'] = bytes.hex(tx_hash)
        tx = {
            'method': method,
            'params': request_params
        }

        response = await self._inner_task.validate_transaction(tx)
        self.assertEqual(response, hex(0))

        make_request = {'transactions': [tx]}
        block_height: int = self._block_height
        block_hash = create_block_hash()

        make_request['block'] = {
            'blockHeight': hex(block_height),
            'blockHash': bytes.hex(block_hash),
            'timestamp': hex(timestamp_us),
            'prevBlockHash': self._prev_block_hash
        }

        precommit_request = {'blockHeight': hex(block_height),
                             'blockHash': bytes.hex(block_hash)}

        invoke_response = await self._inner_task.invoke(make_request)
        tx_results = invoke_response.get('txResults')
        is_commit = False
        if not isinstance(tx_results, dict):
            await self._inner_task.remove_precommit_state(precommit_request)
        elif tx_results[bytes.hex(tx_hash)]['status'] == hex(1):
            is_commit = True
            await self._inner_task.write_precommit_state(precommit_request)
            self._block_height += 1
            self._prev_block_hash = bytes.hex(block_hash)
        else:
            await self._inner_task.remove_precommit_state(precommit_request)

        if tx_results is None:
            return is_commit, invoke_response
        else:
            return is_commit, list(tx_results.values())

    async def _query(self, request: dict, method: str='icx_call'):
        make_request = {'method': method, 'params': request}

        response = await self._inner_task.query(make_request)
        return response

    def test_score_pass(self):
        score_addr_array = []

        is_commit, tx_results = self._run_async(
            self._deploy_zip('test_score_pass', ZERO_SCORE_ADDRESS, self._admin_addr))
        self.assertEqual(is_commit, True)
        score_addr_array.append(tx_results[0]['scoreAddress'])

        value = 1 * 10 ** 18
        is_commit, tx_results = self._run_async(
            self._send_icx_invoke(self._genesis_addr, score_addr_array[0], value)
        )
        self.assertEqual(is_commit, True)

        request = {
            "address": score_addr_array[0]
        }

        response = self._run_async(self._query(request, 'icx_getBalance'))
        self.assertEqual(response, hex(value))

    def test_score_send_to_eoa(self):
        score_addr_array = []

        is_commit, tx_results = self._run_async(
            self._deploy_zip('test_score_to_eoa', ZERO_SCORE_ADDRESS, self._admin_addr))
        self.assertEqual(is_commit, True)
        score_addr_array.append(tx_results[0]['scoreAddress'])

        tmp_addr = str(create_address(AddressPrefix.EOA))

        is_commit, tx_results = self._run_async(
            self._call_method_score(self._admin_addr, score_addr_array[0], 'set_addr_func',
                                    {"addr": tmp_addr}))
        self.assertEqual(is_commit, True)

        value = 1 * 10 ** 18
        is_commit, tx_results = self._run_async(
            self._send_icx_invoke(self._genesis_addr, score_addr_array[0], value)
        )
        self.assertEqual(is_commit, True)

        request = {
            "address": tmp_addr
        }

        response = self._run_async(self._query(request, 'icx_getBalance'))
        self.assertEqual(response, hex(value))

    def test_db_returns(self):
        score_addr_array = []

        is_commit, tx_results = self._run_async(
            self._deploy_zip('test_score_pass1', ZERO_SCORE_ADDRESS, self._admin_addr,
                             {'value': str(self._admin_addr), "value1": str(self._admin_addr)}))
        self.assertEqual(is_commit, True)
        score_addr_array.append(tx_results[0]['scoreAddress'])

        request = {
            "version": hex(self._version),
            "from": str(self._admin_addr),
            "to": score_addr_array[0],
            "dataType": "call",
            "data": {
                "method": "get_value1",
                "params": {}
            }
        }

        response = self._run_async(self._query(request, 'icx_call'))
        self.assertEqual(response, hex(0))

        value = 1
        is_commit, tx_results = self._run_async(
            self._call_method_score(self._admin_addr, score_addr_array[0], 'set_value1',
                                    {"value": hex(value)}))
        self.assertEqual(is_commit, True)

        response = self._run_async(self._query(request, 'icx_call'))
        self.assertEqual(response, hex(value))

        request = {
            "version": hex(self._version),
            "from": str(self._admin_addr),
            "to": score_addr_array[0],
            "dataType": "call",
            "data": {
                "method": "get_value2",
                "params": {}
            }
        }

        response = self._run_async(self._query(request, 'icx_call'))
        self.assertEqual(response, "")

        value = "a"
        is_commit, tx_results = self._run_async(
            self._call_method_score(self._admin_addr, score_addr_array[0], 'set_value2',
                                    {"value": value}))
        self.assertEqual(is_commit, True)

        response = self._run_async(self._query(request, 'icx_call'))
        self.assertEqual(response, value)

        request = {
            "version": hex(self._version),
            "from": str(self._admin_addr),
            "to": score_addr_array[0],
            "dataType": "call",
            "data": {
                "method": "get_value3",
                "params": {}
            }
        }

        response = self._run_async(self._query(request, 'icx_call'))
        self.assertEqual(response, None)

        value = self._prev_block_hash
        is_commit, tx_results = self._run_async(
            self._call_method_score(self._admin_addr, score_addr_array[0], 'set_value3',
                                    {"value": value}))
        self.assertEqual(is_commit, True)

        response = self._run_async(self._query(request, 'icx_call'))
        self.assertEqual(response, f"0x{value}")

        request = {
            "version": hex(self._version),
            "from": str(self._admin_addr),
            "to": score_addr_array[0],
            "dataType": "call",
            "data": {
                "method": "get_value4",
                "params": {}
            }
        }

        response = self._run_async(self._query(request, 'icx_call'))
        self.assertEqual(response, str(self._admin_addr))

        value = str(self._genesis_addr)
        is_commit, tx_results = self._run_async(
            self._call_method_score(self._admin_addr, score_addr_array[0], 'set_value4',
                                    {"value": value}))
        self.assertEqual(is_commit, True)

        response = self._run_async(self._query(request, 'icx_call'))
        self.assertEqual(response, value)

        request = {
            "version": hex(self._version),
            "from": str(self._admin_addr),
            "to": score_addr_array[0],
            "dataType": "call",
            "data": {
                "method": "get_value5",
                "params": {}
            }
        }

        response = self._run_async(self._query(request, 'icx_call'))
        self.assertEqual(response, hex(False))

        value = True
        is_commit, tx_results = self._run_async(
            self._call_method_score(self._admin_addr, score_addr_array[0], 'set_value5',
                                    {"value": hex(value)}))
        self.assertEqual(is_commit, True)

        response = self._run_async(self._query(request, 'icx_call'))
        self.assertEqual(response, hex(value))

        request = {
            "version": hex(self._version),
            "from": str(self._admin_addr),
            "to": score_addr_array[0],
            "dataType": "call",
            "data": {
                "method": "get_value6",
                "params": {}
            }
        }

        response = self._run_async(self._query(request, 'icx_call'))
        self.assertEqual(response, str(self._admin_addr))

        value = str(self._genesis_addr)
        is_commit, tx_results = self._run_async(
            self._call_method_score(self._admin_addr, score_addr_array[0], 'set_value6',
                                    {"value": value}))
        self.assertEqual(is_commit, True)

        response = self._run_async(self._query(request, 'icx_call'))
        self.assertEqual(response, value)

    def test_score_revert(self):
        score_addr_array = []

        is_commit, tx_results = self._run_async(
            self._deploy_zip('test_score_revert', ZERO_SCORE_ADDRESS, self._admin_addr))
        self.assertEqual(is_commit, True)
        score_addr_array.append(tx_results[0]['scoreAddress'])

        value = 1 * 10 ** 18
        raise_exception_start_tag()
        is_commit, tx_results = self._run_async(
            self._send_icx_invoke(self._genesis_addr, score_addr_array[0], value)
        )
        raise_exception_end_tag()
        self.assertEqual(is_commit, False)

        request = {
            "address": score_addr_array[0]
        }

        response = self._run_async(self._query(request, 'icx_getBalance'))
        self.assertEqual(response, hex(0))

    def test_score_no_payable(self):
        score_addr_array = []

        is_commit, tx_results = self._run_async(
            self._deploy_zip('test_score_no_payable', ZERO_SCORE_ADDRESS, self._admin_addr))
        self.assertEqual(is_commit, True)
        score_addr_array.append(tx_results[0]['scoreAddress'])

        value = 1 * 10 ** 18
        raise_exception_start_tag()
        is_commit, tx_results = self._run_async(
            self._send_icx_invoke(self._genesis_addr, score_addr_array[0], value)
        )
        raise_exception_end_tag()
        self.assertEqual(is_commit, False)

        request = {
            "address": score_addr_array[0]
        }

        response = self._run_async(self._query(request, 'icx_getBalance'))
        self.assertEqual(response, hex(0))

    def test_score_pass_link_transfer(self):
        score_addr_array = []

        is_commit, tx_results = self._run_async(
            self._deploy_zip('test_score_pass', ZERO_SCORE_ADDRESS, self._admin_addr))
        self.assertEqual(is_commit, True)
        score_addr_array.append(tx_results[0]['scoreAddress'])

        is_commit, tx_results = self._run_async(
            self._deploy_zip('test_link_score_transfer', ZERO_SCORE_ADDRESS, self._admin_addr))
        self.assertEqual(is_commit, True)
        score_addr_array.append(tx_results[0]['scoreAddress'])

        is_commit, tx_results = self._run_async(
            self._call_method_score(self._admin_addr, score_addr_array[1], 'add_score_func',
                                    {"score_addr": score_addr_array[0]}))
        self.assertEqual(is_commit, True)

        value = 1 * 10 ** 18
        is_commit, tx_results = self._run_async(
            self._send_icx_invoke(self._genesis_addr, score_addr_array[1], value)
        )
        self.assertEqual(is_commit, True)

        request = {
            "address": score_addr_array[0]
        }

        response = self._run_async(self._query(request, 'icx_getBalance'))
        self.assertEqual(response, hex(value))

    def test_score_pass_link_send(self):
        score_addr_array = []

        is_commit, tx_results = self._run_async(
            self._deploy_zip('test_score_pass', ZERO_SCORE_ADDRESS, self._admin_addr))
        self.assertEqual(is_commit, True)
        score_addr_array.append(tx_results[0]['scoreAddress'])

        is_commit, tx_results = self._run_async(
            self._deploy_zip('test_link_score_send', ZERO_SCORE_ADDRESS, self._admin_addr))
        self.assertEqual(is_commit, True)
        score_addr_array.append(tx_results[0]['scoreAddress'])

        is_commit, tx_results = self._run_async(
            self._call_method_score(self._admin_addr, score_addr_array[1], 'add_score_func',
                                    {"score_addr": score_addr_array[0]}))
        self.assertEqual(is_commit, True)

        value = 1 * 10 ** 18
        is_commit, tx_results = self._run_async(
            self._send_icx_invoke(self._genesis_addr, score_addr_array[1], value)
        )
        self.assertEqual(is_commit, True)

        request = {
            "address": score_addr_array[0]
        }

        response = self._run_async(self._query(request, 'icx_getBalance'))
        self.assertEqual(response, hex(value))

    def test_score_no_payable_link_transfer(self):
        score_addr_array = []

        is_commit, tx_results = self._run_async(
            self._deploy_zip('test_score_no_payable', ZERO_SCORE_ADDRESS, self._admin_addr))
        self.assertEqual(is_commit, True)
        score_addr_array.append(tx_results[0]['scoreAddress'])

        is_commit, tx_results = self._run_async(
            self._deploy_zip('test_link_score_transfer', ZERO_SCORE_ADDRESS, self._admin_addr))
        self.assertEqual(is_commit, True)
        score_addr_array.append(tx_results[0]['scoreAddress'])

        is_commit, tx_results = self._run_async(
            self._call_method_score(self._admin_addr, score_addr_array[1], 'add_score_func',
                                    {"score_addr": score_addr_array[0]}))
        self.assertEqual(is_commit, True)

        value = 1 * 10 ** 18
        raise_exception_start_tag()
        is_commit, tx_results = self._run_async(
            self._send_icx_invoke(self._genesis_addr, score_addr_array[1], value)
        )
        raise_exception_end_tag()
        self.assertEqual(is_commit, False)

        request = {
            "address": score_addr_array[0]
        }

        response = self._run_async(self._query(request, 'icx_getBalance'))
        self.assertEqual(response, hex(0))

    def test_score_no_payable_link_send(self):
        score_addr_array = []

        is_commit, tx_results = self._run_async(
            self._deploy_zip('test_score_no_payable', ZERO_SCORE_ADDRESS, self._admin_addr))
        self.assertEqual(is_commit, True)
        score_addr_array.append(tx_results[0]['scoreAddress'])

        is_commit, tx_results = self._run_async(
            self._deploy_zip('test_link_score_send', ZERO_SCORE_ADDRESS, self._admin_addr))
        self.assertEqual(is_commit, True)
        score_addr_array.append(tx_results[0]['scoreAddress'])

        is_commit, tx_results = self._run_async(
            self._call_method_score(self._admin_addr, score_addr_array[1], 'add_score_func',
                                    {"score_addr": score_addr_array[0]}))
        self.assertEqual(is_commit, True)

        value = 1 * 10 ** 18
        raise_exception_start_tag()
        is_commit, tx_results = self._run_async(
            self._send_icx_invoke(self._genesis_addr, score_addr_array[1], value)
        )
        raise_exception_end_tag()
        self.assertEqual(is_commit, False)

        request = {
            "address": score_addr_array[0]
        }

        response = self._run_async(self._query(request, 'icx_getBalance'))
        self.assertEqual(response, hex(0))

    def test_score_revert_link_transfer(self):
        score_addr_array = []

        is_commit, tx_results = self._run_async(
            self._deploy_zip('test_score_revert', ZERO_SCORE_ADDRESS, self._admin_addr))
        self.assertEqual(is_commit, True)
        score_addr_array.append(tx_results[0]['scoreAddress'])

        is_commit, tx_results = self._run_async(
            self._deploy_zip('test_link_score_transfer', ZERO_SCORE_ADDRESS, self._admin_addr))
        self.assertEqual(is_commit, True)
        score_addr_array.append(tx_results[0]['scoreAddress'])

        is_commit, tx_results = self._run_async(
            self._call_method_score(self._admin_addr, score_addr_array[1], 'add_score_func',
                                    {"score_addr": score_addr_array[0]}))
        self.assertEqual(is_commit, True)

        value = 1 * 10 ** 18
        raise_exception_start_tag()
        is_commit, tx_results = self._run_async(
            self._send_icx_invoke(self._genesis_addr, score_addr_array[1], value)
        )
        raise_exception_end_tag()
        self.assertEqual(is_commit, False)

        request = {
            "address": score_addr_array[0]
        }

        response = self._run_async(self._query(request, 'icx_getBalance'))
        self.assertEqual(response, hex(0))

    def test_score_revert_link_send(self):
        score_addr_array = []

        is_commit, tx_results = self._run_async(
            self._deploy_zip('test_score_revert', ZERO_SCORE_ADDRESS, self._admin_addr))
        self.assertEqual(is_commit, True)
        score_addr_array.append(tx_results[0]['scoreAddress'])

        is_commit, tx_results = self._run_async(
            self._deploy_zip('test_link_score_send', ZERO_SCORE_ADDRESS, self._admin_addr))
        self.assertEqual(is_commit, True)
        score_addr_array.append(tx_results[0]['scoreAddress'])

        is_commit, tx_results = self._run_async(
            self._call_method_score(self._admin_addr, score_addr_array[1], 'add_score_func',
                                    {"score_addr": score_addr_array[0]}))
        self.assertEqual(is_commit, True)

        value = 1 * 10 ** 18
        raise_exception_start_tag()
        is_commit, tx_results = self._run_async(
            self._send_icx_invoke(self._genesis_addr, score_addr_array[1], value)
        )
        raise_exception_end_tag()
        self.assertEqual(is_commit, False)

        request = {
            "address": score_addr_array[0]
        }

        response = self._run_async(self._query(request, 'icx_getBalance'))
        self.assertEqual(response, hex(0))


if __name__ == '__main__':
    unittest.main()
