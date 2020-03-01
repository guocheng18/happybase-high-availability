import logging

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(filename)s:%(lineno)d %(message)s",
    datefmt="%m/%d/%Y %H:%M:%S",
)
import time
from happybase import ConnectionPool


pool = ConnectionPool(
    3,
    servers=[
        {"host": "10.6.30.132", "port": 9090},
        {"host": "10.6.30.133", "port": 9090},
    ],
    recovery_delay=5,
)

with pool.connection() as conn:
    while True:
        print(len(conn.table("gru4recx").families()))
        time.sleep(1)
