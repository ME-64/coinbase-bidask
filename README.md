# Coinbase Bid Ask Publisher

Currently the Coinbase Pro Websockets API doesn't provide realtime streaming
for just the current best bid / asks. This has to be reconstructed using the
level two feed. This docker container does just this and allows a user to
publish the resultant feed to a redis database. This is built upon the
`atio-publishers` package which provides the core event loops. The message
receiving, computation, and publishing all happen asyncronously in different
processes for maximum performance. The level two feed often has 100+ messages per
second so performance is key.

To get started, simply use the docker compose file which will spin
up a redis instance and start everything. Alternatively, you can build just the
container with the Dockerfile and provide the redis database seperately.

The list of tickers which are subscribed to can be changed with the
`PRODUCT_ID` environment variables. For example `EXPORT
PRODUCT_ID=BTC-USD,ETH-USD` would subscribe to both the ETH and BTC feed. Note,
each order book state and connection is maintained in seperate processes to not
overload a single websockets feed.

## Getting Started

To simply test this repository - you can use the `docker-compose.yml` file
which will spin up the `bid-ask` container, along with a redis instance.

```
git clone https://github.com/ME-64/coinbase-bidask`
cd coinbase-bidask
docker compose up -d
```

After doing this, you can see the data is being published to redis either via
your local installation of `redis-cli`, or via the one in the container.


```
docker exec -it coinbase-bidask-redis-1 bash

redis-cli

PSUBSCRIBE BID_ASK.*
```

This will subscribe you to all messages relating to the bid ask channel.

You can also fetch current values, which are stored in a key.

```
redis-cli

HGETALL CBPRO.BTC-USD
```


