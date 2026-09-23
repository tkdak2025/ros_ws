from pathlib import Path

from setuptools import find_packages, setup

package_name = 'cable_pkg'


def resource_files(root):
    """Return ROS share destinations for non-Python package resources."""
    base = Path(root)
    files = []
    for path in base.rglob('*'):
        if not path.is_file() or '__pycache__' in path.parts:
            continue
        relative_parent = path.relative_to(base).parent
        destination = Path('share') / package_name / base.name / relative_parent
        files.append((str(destination), [str(path)]))
    return files

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    package_data={},
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ] + resource_files('config') + resource_files('cable_pkg/recipe') + resource_files('launch'),
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='hun',
    maintainer_email='tkdak2025@gmail.com',
    description='M0609 + RG2 케이블/커넥터 체결 검사 PoC',
    license='Apache-2.0',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'main_sequence = cable_pkg.sequence.seq_00_main_work.run:main',
            'inspection_judgment = cable_pkg.sequence.seq_06_inspection_judgment.node:main',
            'inspection_sequence = cable_pkg.sequence.inspection.run:main',
            'manual_check = cable_pkg.diagnostics.manual_check:main',
        ],
    },
)
