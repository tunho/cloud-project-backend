from abc import ABC, abstractmethod

class GameHandler(ABC):
    @abstractmethod
    def start_turn(self, room_id: str, gs):
        pass

    @abstractmethod
    def handle_action(self, room_id: str, action: str, data: dict, sid: str):
        pass
