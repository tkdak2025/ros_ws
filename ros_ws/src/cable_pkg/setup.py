from setuptools import find_packages, setup

package_name = 'cable_pkg'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
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
            'pull_test_logger = cable_pkg.pull_test_logger:main',
        ],
    },
)
