from redis_conn import REDIS_CONN_CONF
from redis_keys import polymarket_consolidated_trade_vol_key_f, polymarket_seed_trade_lock, polymarket_base_trade_vol_key_f
from message_models import (
    PolymarketTradeSnapshot, UniswapPairTotalReservesSnapshot, EpochBase, PolymarketSeedTradeVolumeRequest,
    PolymarketTradeVolumeBase, PolymarketTradeSnapshotTotalTrade
)
from callback_modules.helpers import AuditProtocolCommandsHelper
from functools import reduce
from pydantic import ValidationError
from typing import List
from uuid import uuid4
import redis
import logging
import json
import time


@transient()
class TradeVolumeSeederTestActor(Actor):
    def receiveMessage(self, msg, sender):
        if isinstance(msg, ActorExitRequest) or isinstance(msg, PoisonMessage) or isinstance(msg, WakeupMessage):
            return
        redis_conn = redis.Redis(**REDIS_CONN_CONF)
        redis_seeding_lock = polymarket_seed_trade_lock.format(msg.contract)
        redis_conn.set(redis_seeding_lock, str(True))
        seed_trade_vol: PolymarketTradeVolumeBase = seed_trade_volume(contract_address=msg.contract, chain_height=msg.chainHeight)
        if seed_trade_vol:

            redis_conn.set(
                polymarket_base_trade_vol_key_f.format(msg.contract),
                seed_trade_vol.json()
            )
            logging.debug("Marketmaker contract %s | Base Trade volume set to %s", msg.contract, seed_trade_vol.tradeVolume)
            redis_conn.set(
                polymarket_consolidated_trade_vol_key_f.format(msg.contract),
                seed_trade_vol.json()
            )
            logging.debug("Marketmaker contract %s | Consolidated Trade volume set to %s", msg.contract, seed_trade_vol.tradeVolume)
        else:
            logging.error('Marketmaker contract %s | Failed to seed Trade volume', msg.contract)
        redis_conn.delete(redis_seeding_lock)


@transient()
class TradeVolumeSummationTestActor(Actor):
    def receiveMessage(self, msg: UniswapPairTotalReservesSnapshot, sender):
        if isinstance(msg, ActorExitRequest) or isinstance(msg, PoisonMessage) or isinstance(msg, WakeupMessage):
            return
        logging.debug('Launched TradeVolumeSummationTestActor')
        try:
            redis_conn = redis.Redis(**REDIS_CONN_CONF)
        except Exception as e:
            logging.error('Error connecting to redis: %s', e, exc_info=True)
            return
        logging.debug('Checking if seed lock exists')
        # check last cached
        trade_vol_cache_key = polymarket_consolidated_trade_vol_key_f.format(msg.contract)
        queued_trade_vol_epochs_redis_q = f'polymarket:marketMaker:{msg.contract}:queuedTradeVolumeEpochs'
        trades_snapshot = PolymarketTradeSnapshot()
        # TODO: check if seeding is already underway
        redis_seeding_lock = polymarket_seed_trade_lock.format(msg.contract)
        logging.debug('Checking if seed lock exists')
        if redis_conn.exists(redis_seeding_lock):
            redis_conn.rpush(
                queued_trade_vol_epochs_redis_q,
                msg.json()
            )
            logging.debug(f'Enqueued trade volume epoch broadcast ID {msg.broadcast_id} '
                          f'for summation until trade volume seed lock is released: {msg}')
            return
        # check if base trade volume has been set
        if not redis_conn.exists(trade_vol_cache_key):
            seed_height = msg.chainHeightRange.begin - 1
            logging.debug(
                'Processing base level of trade volume for contract %s until chain height %s',
                msg.contract,
                seed_height
            )
            # ask the actor system to spawn the seeder actor and not from this current transient actor
            asys = ActorSystem('multiprocTCPBase')  # , logDefs=logcfg_thespian_main)
            seeder = asys.createActor('callback_modules.tests.TradeVolumeSeederTestActor')
            # seeder = asys.createActor('TradeVolumeSeederActor')
            self.send(seeder, PolymarketSeedTradeVolumeRequest(contract=msg.contract, chainHeight=seed_height))
            # enqueue the trade volume epoch that has arrived
            redis_conn.rpush(
                queued_trade_vol_epochs_redis_q,
                msg.json()
            )
            logging.debug(f'Enqueued trade volume epoch broadcast ID {msg.broadcast_id} '
                          f'for summation until base trade volume is seeded: {msg}')
        else:
            tentative_max_block_height = msg.chainHeightRange.begin
            logging.debug('Checking if there are any enqueued trade volume epochs: %s', queued_trade_vol_epochs_redis_q)
            enqueued_trade_vol = 0
            shortlisted_epochs: List[UniswapPairTotalReservesSnapshot] = list()
            to_be_reenqueued_epochs = list()
            while True:
                enqueued_epoch = redis_conn.lpop(queued_trade_vol_epochs_redis_q)
                if not enqueued_epoch:
                    break
                try:
                    epoch_details = UniswapPairTotalReservesSnapshot.parse_raw(enqueued_epoch)
                except ValidationError:
                    continue
                logging.debug('Found enqueued epoch for zset: %s | %s', queued_trade_vol_epochs_redis_q, epoch_details)
                # create a continuous range of block heights needed
                epoch_details_obj = UniswapPairTotalReservesSnapshot(**json.loads(epoch_details))
                if epoch_details_obj.chainHeightRange.end <= tentative_max_block_height:
                    shortlisted_epochs.append(epoch_details_obj)
                    logging.debug(
                        'Shortlisting trade volume epoch to be summed into consolidated trade volume: %s',
                        epoch_details_obj
                    )
                    trades_snapshot.buys.extend(epoch_details_obj.buys)
                    trades_snapshot.sells.extend(epoch_details_obj.sells)
                if epoch_details_obj.chainHeightRange.begin > msg.chainHeightRange.end:
                    # this is where epochs with their ends overlapping with the present epoch wont be re-enqueued
                    to_be_reenqueued_epochs.append(enqueued_epoch)
            if shortlisted_epochs:
                shortlisted_epochs_summation = reduce(lambda x, y: x.tradeVolume + y.tradeVolume, shortlisted_epochs)
                enqueued_trade_vol += shortlisted_epochs_summation
                logging.debug('Adding tradeVolume from queued up epochs for marketMaker %s: %s', msg.contract,
                              enqueued_trade_vol)
            prev_trade_vol_ = redis_conn.get(trade_vol_cache_key)
            prev_trade_vol_obj: PolymarketTradeVolumeBase = PolymarketTradeVolumeBase.parse_raw(prev_trade_vol_)
            # fill previous accumulated trade volume in snapshot object
            trades_snapshot.previousCumulativeTrades = prev_trade_vol_obj.dict()
            trades_snapshot.buys.extend(msg.buys)
            trades_snapshot.sells.extend(msg.sells)
            trades_snapshot.totalTrade = PolymarketTradeSnapshotTotalTrade(tradeVolume=msg.tradeVolume + enqueued_trade_vol,
                                                                           chainHeight=msg.chainHeightRange.end)
            logging.debug('Adding reported tradeVolume from epoch %s to previously set consolidated trade volume: %s', msg,
                          prev_trade_vol_obj)
            new_trade_vol = PolymarketTradeVolumeBase(
                contract=prev_trade_vol_obj.contract,
                tradeVolume=prev_trade_vol_obj.tradeVolume + msg.tradeVolume + enqueued_trade_vol,
                chainHeight=msg.chainHeightRange.end,
                timestamp=float(f'{time.time(): .4f}')
            )
            redis_conn.set(
                trade_vol_cache_key,
                new_trade_vol.json()
            )
            if to_be_reenqueued_epochs:
                [redis_conn.rpush(queued_trade_vol_epochs_redis_q, x) for x in to_be_reenqueued_epochs]
                logging.debug('Reenqueued trade volume epochs for contract %s: %s', msg.contract, to_be_reenqueued_epochs)
            # send snapshot to audit protocol
            market_id = get_market_data_by_address(msg.contract)
            if market_id:
                AuditProtocolCommandsHelper.set_diff_rule(market_id)
                payload = {'trades': trades_snapshot.dict()}
                AuditProtocolCommandsHelper.commit_payload(pair_contract_address=market_id, stream='trades', report_payload=payload)


if __name__ == '__main__':
    pass
    # asys = ActorSystem('multiprocTCPBase', logDefs=logcfg_thespian_main)
    # sum_actor = asys.createActor('callback_modules.tests.TradeVolumeSummationTestActor')
    # msg = PolymarketEpochTradeVolume(
    #     contract='0x78d5ada156768521c8f9a9bac02f20d1c4db01d8',
    #     tradeVolume=0.0,
    #     chainHeightRange=EpochBase(begin=15495765, end=15495825),
    #     broadcast_id=str(uuid4()),
    #     buys=[],
    #     sells=[],
    #     timestamp=1623252088.1262
    # )
    # asys.tell(sum_actor, msg)
