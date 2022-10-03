import logging
import os
import signal
import time

import requests

# Env vars
val = os.getenv('val_key', 'evmosvalcons1nsczfx3qr75f3anp4lklcanm585x7vwfuw3mt4')
routing_key = os.getenv('routing_key')

# Logger
logger = logging.getLogger()
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter('[%(asctime)s][%(levelname)s]: %(message)s', '%H:%M:%S'))
logger.setLevel(logging.DEBUG)
logger.addHandler(handler)

# Validate env vars
if routing_key is None:
    logger.error('The routing key is missing!')
    raise (SystemExit(1))

# Set up globals
LAST_ALERT = None
CURRENT_BLOCK = None
BLOCKS_MISSED = None
LAST_UPDATE = None
RUNNING = True

MAX_TIMEOUT = 120

# Evmos api
urls = [
    'https://rest.bd.evmos.org:1317', 'https://api-evmos-ia.cosmosia.notional.ventures',
    'https://evmos-api.polkachu.com', 'https://rest-evmos.ecostake.com'
]


def get_missed_blocks(url):
    try:
        endpoint = f'{url}/cosmos/slashing/v1beta1/signing_infos/{val}'
        res = requests.get(endpoint, timeout=2).json()
        logger.debug(f'Getting missed blocks from {endpoint}')
        return res['val_signing_info']['missed_blocks_counter']
    except Exception:
        return None


def get_height(url):
    try:
        endpoint = f'{url}/cosmos/base/tendermint/v1beta1/blocks/latest'
        res = requests.get(endpoint, timeout=2).json()
        logger.debug(f'Getting height from {endpoint}')
        return int(res['block']['header']['height'])
    except Exception:
        return None


def get_status():
    global CURRENT_BLOCK
    global LAST_UPDATE
    global BLOCKS_MISSED

    i = 0
    height = None
    while height is None and i < len(urls):
        height = get_height(urls[i])
        i = i + 1


    if i == len(urls):
        if LAST_UPDATE is None:
            # All endpoints are invalid
            logger.info('Sending alert: All endpoints are invalid')
            send_alert(text='All endpoints are invalid')
            return False

        if time.time() - LAST_UPDATE > MAX_TIMEOUT:
            # After MAX_TIMEOUT we didn't get a valid endpoint
            logger.info('Sending alert: No valid response')
            send_alert(text=f'No valid response after {MAX_TIMEOUT} seconds')
            return False

        return False

    if CURRENT_BLOCK is None:
        CURRENT_BLOCK = height
    else:
        if height < CURRENT_BLOCK:
            # The height is lower than our last stored height (endpoints are not in sync)
            logger.debug('The height is lower than our last stored height (endpoints are not in sync)')
            return False
        CURRENT_BLOCK = height

    missed = get_missed_blocks(urls[i])
    if missed is None:
        # Error on the request, if we fail for MAX_TIMEOUT, a notification will be send_alert
        logger.debug(f'Failed to get the missing blocks from {urls[i]}')
        return False

    LAST_UPDATE = time.time()
    BLOCKS_MISSED = missed

    if int(BLOCKS_MISSED) > 2000:
        logger.info(f'Sending alert: Missing blocks: {BLOCKS_MISSED}!')
        send_alert(blocks_missed=BLOCKS_MISSED)
        return False

    return True


# Pager duty
def generate_body(blocks_missed='?', text='Missing blocks!'):
    return {
        'payload': {
            'summary': text,
            'severity': 'critical',
            'source': 'Hanchon.live',
            'component': 'validator',
            'custom_details': {
                'blocks missed': str(blocks_missed),
            }
        },
        'routing_key':
        str(routing_key),
        'event_action':
        'trigger',
        'client':
        'Validator Monitoring Service',
        'client_url':
        'https://hanchon.live',
        'links': [{
            'href': 'https://www.mintscan.io/evmos/validators/evmosvaloper1dgpv4leszpeg2jusx2xgyfnhdzghf3rf0qq22v',
            'text': 'Mintscan link!'
        }],
        'images': [{
            'src': 'https://images.pexels.com/photos/1805164/pexels-photo-1805164.jpeg',
            'href': 'https://google.com',
            'alt': 'There is no need for this'
        }]
    }


def send_alert(blocks_missed='?', text='Missing blocks!'):
    global LAST_ALERT

    if LAST_ALERT is not None:
        if time.time() - LAST_ALERT > 5 * 60:
            # Only send 1 alert every 5min
            return False

    x = requests.post('https://events.eu.pagerduty.com/v2/enqueue',
                      json=generate_body(blocks_missed=blocks_missed, text=text))
    while x.status_code != 202:
        logger.error(f'Waiting 1 min to resend the alert, status code: {x.status_code}')
        time.sleep(60 * 1)
        x = requests.post('https://events.eu.pagerduty.com/v2/enqueue',
                          json=generate_body(blocks_missed=blocks_missed, text=text))

    logger.info('Alert sent!')
    LAST_ALERT = time.time()
    return True


# Handel control + c
def kill_handler(signum, frame):
    global RUNNING
    _ = signum
    _ = frame
    logger.info('Closing the program...')
    RUNNING = False


if __name__ == '__main__':
    signal.signal(signal.SIGINT, kill_handler)
    while RUNNING:
        get_status()
        # Wait at least 2 seconds for the next block
        time.sleep(2)

    raise (SystemExit(0))
