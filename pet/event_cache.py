"""窗口生命周期内的有界事件去重，不保存业务数据。"""

from collections import OrderedDict


class RecentEvents:
    """保存最近处理的事件 ID；重连复用，容量外事件允许再次处理。"""

    def __init__(self, capacity: int = 1024) -> None:
        if capacity < 1:
            raise ValueError("事件缓存容量必须为正数")
        self.capacity = capacity
        self._ids: OrderedDict[str, None] = OrderedDict()

    def contains(self, event_id: str) -> bool:
        """已处理事件命中时刷新最近使用顺序。"""
        if event_id not in self._ids:
            return False
        self._ids.move_to_end(event_id)
        return True

    def remember(self, event_id: str) -> None:
        """处理成功后记录，超过容量则淘汰最久未使用的 ID。"""
        self._ids[event_id] = None
        self._ids.move_to_end(event_id)
        if len(self._ids) > self.capacity:
            self._ids.popitem(last=False)
