from iconservice import *


class TestInterface(InterfaceScore):
    @interface
    def writable_func(self, value: int) -> None: pass

    @interface
    def readonly_func(self) -> int: pass


class SampleToken(IconScoreBase):
    _TEST = 'test'
    _SCORE_ADDR = 'score_addr'

    def __init__(self, db: IconScoreDatabase) -> None:
        super().__init__(db)
        self._value = VarDB(self._TEST, db, value_type=int)
        self._addr_score = VarDB(self._SCORE_ADDR, db, value_type=Address)

    def on_install(self) -> None:
        super().on_install()

    def on_update(self) -> None:
        super().on_update()

    @external(readonly=True)
    def hello(self) -> str:
        print(f'Hello, world!')
        return "Hello"

    @external(readonly=False)
    def add_score_func(self, score_addr: Address) -> None:
        self._addr_score.set(score_addr)

    @external(readonly=False)
    def writable_func(self, value: int) -> None:
        self._value.set(value)
        pass

    @external(readonly=True)
    def readonly_func(self) -> int:
        return self._value.get()
