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

from .icx_account import Account
from .icx_config import BALANCE_BYTE_SIZE, DATA_BYTE_ORDER
from ..base.address import Address


class IcxStorage(object):
    """Icx coin state manager embedding a state db wrapper
    """

    def __init__(self, db: 'ContextDatabase') -> None:
        """Constructor

        :param db: (Database) state db wrapper
        """
        self.__db = db

    @property
    def db(self) -> 'ContextDatabase':
        """Returns state db wrapper.

        :return: (Database) state db wrapper
        """
        return self.__db

    def get_text(self, context: 'IconScoreContext', name: str) -> str:
        """Return text format value from db

        :return: (str or None)
            text value mapped by name
            default encoding: utf8
        """
        key = name.encode()
        value = self.__db.get(context, key)
        if value:
            return value.decode()
        else:
            return None

    def put_text(self,
                 context: 'IconScoreContext',
                 name: str,
                 text: str) -> None:
        """save text to db with name as a key
        All text are utf8 encoded.

        :param context:
        :param name: db key
        :param text: db value
        """
        key = name.encode()
        value = text.encode()
        self.__db.put(context, key, value)

    def get_account(self,
                    context: 'IconScoreContext',
                    address: Address) -> Account:
        """Returns the account indicated by address.

        :param context:
        :param address: account address
        :return: (Account)
            If the account indicated by address is not present,
            create a new account.
        """
        account = None

        key = address.body
        value = self.__db.get(context, key)

        if value:
            account = Account.from_bytes(value)
        else:
            account = Account()

        account.address = address
        return account

    def put_account(self,
                    context: 'IconScoreContext',
                    address: Address,
                    account: Account) -> None:
        """Put account info to db.

        :param address: account address
        :param account: account to save
        """
        key = address.body
        value = account.to_bytes()
        self.__db.put(context, key, value)

    def delete_account(self,
                       context: 'IconScoreContext',
                       address: Address) -> None:
        """Delete account info from db.

        :param context:
        :param address: account address
        """
        key = address.body
        self.__db.delete(context, key)

    def get_total_supply(self, context: 'IconScoreContext') -> int:
        """Get the total supply

        :return: (int) coin total supply in loop (1 icx == 1e18 loop)
        """
        key = b'total_supply'
        value = self.__db.get(context, key)

        amount = 0
        if value:
            amount = int.from_bytes(value, DATA_BYTE_ORDER)

        return amount

    def put_total_supply(self,
                         context: 'IconScoreContext',
                         value: int) -> None:
        """Save the total supply to db

        :param context:
        :param value: coin total supply
        """
        key = b'total_supply'
        value = value.to_bytes(BALANCE_BYTE_SIZE, DATA_BYTE_ORDER)
        self.__db.put(context, key, value)

    def is_address_present(self,
                           context: 'IconScoreContext',
                           address: Address) -> bool:
        """Check whether value indicated by address is present or not.

        :param context:
        :param address: account address
        :return: True(present) False(not present)
        """
        key = address.body
        value = self.__db.get(context, key)

        return bool(value)

    def close(self,
              context: 'IconScoreContext') -> None:
        """Close the embedded database.

        :param context:
        """
        if self.__db:
            self.__db.close(context)
            self.__db = None
