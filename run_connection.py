import logging

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(filename)s:%(lineno)d %(message)s",
    datefmt="%m/%d/%Y %H:%M:%S",
)
import time

from happybase import Connection


haconn = Connection(
    servers=[
        {"host": "10.6.30.133", "port": 9090},
        {"host": "10.6.30.134", "port": 9090},
    ],
    autoconnect=False,
)

haconn.open()

while True:
    print(haconn.is_table_enabled("gru4rec"))
    time.sleep(3)


