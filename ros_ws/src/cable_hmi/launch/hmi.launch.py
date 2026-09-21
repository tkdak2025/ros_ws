"""
HMI 실행 launch.

  가상 테스트 : ros2 launch cable_hmi hmi.launch.py
  실제 통합   : ros2 launch cable_hmi hmi.launch.py mock:=false
                (실제 검사 노드가 cable_hmi/interface.py 의 토픽을 제공해야 한다)
"""

import os

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    """HMI 와 (선택) mock 검사 노드를 띄운다."""
    mock = LaunchConfiguration('mock')
    random_outcomes = LaunchConfiguration('random_outcomes')
    namespace = LaunchConfiguration('namespace')
    recipe_db = LaunchConfiguration('recipe_db')

    return LaunchDescription([
        DeclareLaunchArgument('mock', default_value='true',
                              description='가상 검사 노드를 함께 실행'),
        DeclareLaunchArgument('random_outcomes', default_value='false',
                              description='mock 의 Point 결과를 무작위로'),
        DeclareLaunchArgument('namespace', default_value='',
                              description='HMI/검사 노드 공통 namespace'),
        # 레시피 정보(케이블·판정 기준) SQLite. 읽을 수 있으면 mock 이 거기서 Recipe 를 가져오고,
        # 파일이나 뷰가 없으면 경고 후 내장 예제 레시피로 동작한다. '' 이면 DB 를 쓰지 않는다.
        DeclareLaunchArgument(
            'recipe_db', default_value=os.path.expanduser('~/ros_ws/results/inspection.db')),
        # 레시피 JSON 폴더 - '통합 조회' 탭이 DB 와 위치 정보를 대조할 때 쓴다.
        DeclareLaunchArgument(
            'recipe_dir',
            default_value=os.path.expanduser('~/ros_ws/recipe_prototype/recipe/examples')),
        Node(
            package='cable_hmi', executable='mock_inspection_node', namespace=namespace,
            output='screen', condition=IfCondition(mock),
            parameters=[{'random_outcomes': ParameterValue(random_outcomes, value_type=bool),
                         'recipe_db': ParameterValue(recipe_db, value_type=str)}],
        ),
        # 검사 결과를 같은 DB 파일의 inspection_result 테이블에 저장한다 (mock:=false 여도 띄운다).
        Node(package='cable_hmi', executable='result_recorder_node', namespace=namespace,
             output='screen',
             parameters=[{'result_db': ParameterValue(recipe_db, value_type=str)}]),
        Node(package='cable_hmi', executable='hmi', namespace=namespace, output='screen',
             parameters=[{      # '통합 조회' 탭이 읽을 위치
                 'recipe_db': ParameterValue(recipe_db, value_type=str),
                 'recipe_dir': ParameterValue(
                     LaunchConfiguration('recipe_dir'), value_type=str),
             }]),
    ])
