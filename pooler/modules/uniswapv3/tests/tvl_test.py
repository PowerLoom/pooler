

import asyncio


if __name__ == '__main__':
    pair_address = '0x7b73644935b8e68019ac6356c40661e1bc315860'
    loop = asyncio.get_event_loop()
    data = loop.run_until_complete(
        (pair_address, loop),
    )
    print(f'\n\n{data}\n')
