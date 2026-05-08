from __future__ import annotations

from pathlib import Path
import numpy as np


class DataExporter:
    """Exports plot data to text files."""

    @staticmethod
    def export_matrix(
        filepath: str | Path,
        data: np.ndarray,
        headers: list[str],
        delimiter: str = "\t",
    ) -> None:
        """Export matrix to text file with headers."""
        filepath = Path(filepath)
        np.savetxt(
            fname=filepath,
            X=data,
            delimiter=delimiter,
            header=delimiter.join(headers),
            comments="",
        )

    @staticmethod
    def export_csv(
        filepath: str | Path,
        data: np.ndarray,
        headers: list[str],
    ) -> None:
        """Export matrix to CSV file."""
        DataExporter.export_matrix(filepath, data, headers, delimiter=",")
