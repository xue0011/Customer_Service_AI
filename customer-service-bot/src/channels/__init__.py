from .base import ChannelAdapter
from .dewu import DewuAdapter
from .jd import JdAdapter
from .pinduoduo import PinduoduoAdapter
from .taobao import TaobaoAdapter

__all__ = [
    "ChannelAdapter",
    "TaobaoAdapter",
    "PinduoduoAdapter",
    "JdAdapter",
    "DewuAdapter",
]
