from decimal import Decimal
import logging
import os
from typing import Type, Literal

import aiohttp
from atio_publishers.websockets import BaseWSClient, Publisher, WSManager, Worker # type: ignore
import pandas as pd
from sortedcontainers import SortedDict
import ujson

DoneWork = tuple[Literal["HEARTBEAT", "BID_ASK"], str, str] | tuple[Literal["HEARTBEAT", "BID_ASK"], str, dict] | None
PubWork = tuple[Literal["HEARTBEAT", "BID_ASK"], str, str] | tuple[Literal["HEARTBEAT", "BID_ASK"], str, dict]

class WSClient(BaseWSClient):

    def __init__(self, worker: Type[Worker], publisher: Type[Publisher], product_id: str):# {{{
        self.product_id = product_id
        BaseWSClient.__init__(self, ws_url=os.environ['CB_WS_URL'],
                redis_url=os.environ['REDIS_URL'], worker=worker, publisher=publisher)# }}}

    async def subscribe(self) -> None:# {{{
        self._started.wait() # type: ignore
        log.info(f'subscribing to {os.environ["PRODUCT_ID"]}')
        js: dict = {'type': 'subscribe',
                'channels': [
                    {'name': 'level2', 'product_ids': [self.product_id]},
                    {'name': 'heartbeat', 'product_ids': [self.product_id]}
                            ]}
        await self.ws.send_str(ujson.dumps(js))
        log.info('subscription sent') # }}}

    async def on_start(self) -> None:# {{{
        await self.subscribe()# }}}

    async def on_message(self, msg: aiohttp.WSMessage) -> None:# {{{
        log.debug(f'msg received')
        log.debug(f'pub: {self.publisher.pub_queue.qsize()}; work: {self.worker.work_queue.qsize()}')
        msg_data: str = msg.data
        jsmsg: dict = ujson.loads(msg_data)

        log.debug('putting work in work queue')
        self.work_queue.put(jsmsg) # type: ignore
            # }}}



class BAPublisher(Publisher):
    def __init__(self, *args, **kwargs):# {{{
        Publisher.__init__(self, *args, **kwargs)# }}}

    async def publish(self, work: PubWork):# {{{
        if work[0] == 'BID_ASK':
            async with self.redis.pipeline() as pipe:
                pipe.publish('BID_ASK.CBPRO.' + work[1], ujson.dumps(work[2]))
                pipe.hset('CBPRO.' + work[1], mapping=work[2])
                await pipe.execute()
            log.debug(f'published {work[0]} to {work[1]}')
        elif work[0] == 'HEARTBEAT':
            await self.redis.hset('CBPRO.' + work[1], key='hb', value=work[2])
            log.debug(f'published {work[0]} to {work[1]}')
            # }}}

class BAWorker(Worker):

    def __init__(self, *args, **kwargs):# {{{
        Worker.__init__(self, *args, **kwargs)
        self.zero: Decimal = Decimal('0')
        # setup last sent bid and ask with a default value
        self.lb: Decimal = Decimal('inf')
        self.la: Decimal = Decimal('inf')
        # }}}

    def do_work(self, msg: dict) -> DoneWork:# {{{
        """maintains the orderbook state and pushes heartbeat messages through"""

        log.debug(f'doing work on {msg["type"]}')
        # these are ordered in expected frequency of receiving
        if msg['type'] == 'l2update':
            self.update_orderbook(msg)
            bbo: dict = self.get_bbo()
            if bbo:
                # return ('BID_ASK', 'BID_ASK.CBPRO.' + msg['product_id'], bbo)
                return ('BID_ASK', msg['product_id'], bbo)
        elif msg['type'] == 'heartbeat':
            # return ('HEARTBEAT', 'BID_ASK.CBPRO.' + msg['product_id'], pd.to_datetime(msg['time'], utc=True).strftime('%s%f'))
            return ('HEARTBEAT', msg['product_id'], pd.to_datetime(msg['time'], utc=True).strftime('%s%f'))

        elif msg['type'] == 'snapshot':
            self.setup_orderbook(msg)
            bbo: dict = self.get_bbo()
            if bbo:
                return ('BID_ASK', msg['product_id'], bbo)
        elif msg['type'] == 'error':
            log.critical('received error from coinbase {msg}')
            self._started.clear() # type: ignore
        # }}}

    def setup_orderbook(self, msg: dict) -> None:# {{{
        self.timestamp: str = pd.to_datetime('now', utc=True).strftime('%s%f') # type: ignore
        self.bids: SortedDict = SortedDict({Decimal(b[0]): b[1] for b in msg['bids']})
        self.asks: SortedDict = SortedDict({Decimal(b[0]): b[1] for b in msg['asks']})# }}}

    def update_orderbook(self, msg: dict) -> None:# {{{
        self.timestamp: str = pd.to_datetime(msg['time'], utc=True).strftime('%s%f')
        [self.apply_orderbook_change(x) for x in msg['changes']]# }}}

    def apply_orderbook_change(self, change):# {{{
        change[1] = Decimal(change[1])
        if change[0] == 'buy':
            if Decimal(change[2]) == self.zero:
                self.bids.pop(change[1])
            else:
                self.bids[change[1]] = change[2]
        elif change[0] == 'sell':
            if Decimal(change[2]) == self.zero:
                self.asks.pop(change[1])
            else:
                self.asks[change[1]] = change[2]# }}}

    def get_bbo(self) -> dict[str, str]:# {{{
        b: Decimal = self.bids.keys()[-1]
        a: Decimal = self.asks.keys()[0]
        if (b != self.lb) or (a != self.la):
            self.lb: Decimal = b
            self.la: Decimal = a
            return {'t': self.timestamp,
                    'a': str(a),
                    'b': str(b)}
        else:
            return {}# }}}


def create_ws_clients() -> list[Type[BaseWSClient]]:# {{{
    pids: str = os.environ['PRODUCT_ID']
    pids_list: list[str] = pids.split(',')

    wscs = []
    for pid in pids_list:
        wsc: WSClient = WSClient(worker=BAWorker, publisher=BAPublisher, product_id=pid)
        wscs.append(wsc)
    return wscs# }}}

if __name__ == '__main__':

    log: logging.Logger = logging.getLogger('atio')
    hndlr: logging.StreamHandler = logging.StreamHandler()
    hndlr.setFormatter(logging.Formatter('%(asctime)s %(name)s:%(process)d - %(levelname)s - %(funcName)s - %(message)s',
        datefmt='%d %H:%M:%S'))
    log.addHandler(hndlr)
    log.setLevel('INFO')

    clients: list = create_ws_clients()
    manager: WSManager = WSManager(clients)
    manager.run()


    # from multiprocessing import log_to_stderr
    # import multiprocessing_logging
    # mp_logg = log_to_stderr('DEBUG')
    # mp_logg.addHandler(hndlr)
    # multiprocessing_logging.install_mp_handler()
    # loop: asyncio.AbstractEventLoop = asyncio.get_event_loop()
    # ws: WSClient = WSClient(worker=BAWorker, publisher=Publisher)
    # loop.create_task(ws.start())
    # loop.run_forever()

