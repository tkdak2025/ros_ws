from pathlib import Path
from setuptools import setup, find_packages



def resources(folder, destination, suffixes=None):
    root = Path(folder)
    groups = {}

    for path in root.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue

        if suffixes is not None and path.suffix not in suffixes:
            continue

        key = str(Path(destination) / path.relative_to(root).parent)
        groups.setdefault(key, []).append(str(path))

    return list(groups.items())



setup(
    name="cable_inspection", version="0.1.0",
    packages=find_packages(exclude=["test", "test.*"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/cable_inspection"]),
        ("share/cable_inspection", ["package.xml", "README.md"]),
    ] + resources("launch", "share/cable_inspection/launch")
      + resources("config", "share/cable_inspection/config")
      + resources("cable_inspection/recipe", "share/cable_inspection/recipe", suffixes={".json"}),
    install_requires=["setuptools"], zip_safe=True,
    maintainer="hun", maintainer_email="tkdak2025@gmail.com",
    description="CCCIS robot control and inspection sequences",
    license="Apache-2.0",
    entry_points={"console_scripts": [
        "main_sequence = cable_inspection.sequence.main.node_main:main",
        "sequence_console = cable_inspection.sequence.main.console_main:main",
        "inspection_judgment = cable_inspection.sequence.inspection.node_inspection:main",
        "manual_check = cable_inspection.diagnostics.manual_check:main",
    ]},
)
