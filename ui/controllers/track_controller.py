"""Контроллер взаимодействия со списком треков."""

from PyQt6.QtCore import QObject, pyqtSignal


class TrackController(QObject):
    play_requested = pyqtSignal(object)
    track_activated = pyqtSignal(object)
    clear_search_requested = pyqtSignal()

    def __init__(self, track_list, parent=None):
        super().__init__(parent)
        self.track_list = track_list
        track_list.track_play_requested.connect(self.play_requested)
        track_list.track_activated.connect(self.track_activated)
        track_list.clear_search_requested.connect(self.clear_search_requested)

    def build_queue(self) -> list:
        model = self.track_list.model
        return [
            track
            for row in range(model.rowCount())
            if (track := model.get_track(row)) is not None
        ]

    def set_playing(self, video_id: str) -> None:
        self.track_list.set_playing(video_id)

    def refresh_track(self, track_id: int) -> None:
        self.track_list.model.update_track(track_id)

    def set_progress(self, track_id: int, percent: int) -> None:
        self.track_list.set_track_progress(track_id, percent)

    def clear_progress(self, track_id: int) -> None:
        self.track_list.model.clear_progress(track_id)
