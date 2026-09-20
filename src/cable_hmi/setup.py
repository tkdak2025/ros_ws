from glob import glob

from setuptools import find_packages, setup

package_name = 'cable_hmi'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    package_data={package_name: ['*.ui']},
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch', glob('launch/*.launch.py')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='hun',
    maintainer_email='tkdak2025@gmail.com',
    description='케이블 체결 검사 PyQt5 HMI (ROS 2 pub/sub 전용) + 가상 검사 노드',
    license='Apache-2.0',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'hmi = cable_hmi.hmi_main:main',
            'mock_inspection_node = cable_hmi.mock_inspection_node:main',
            'robot_monitor_node = cable_hmi.robot_monitor_node:main',
        ],
    },
)
