"""Recipe 실행 노드와 ROS 메시지 변환 API. 외부 HMI 계약은 호출 측에서 유지한다."""

from copy import deepcopy
from rclpy.node import Node
from rosidl_runtime_py.convert import message_to_ordereddict
from rosidl_runtime_py.set_message import set_message_fields
from cable_interfaces.msg import InspectionRecipe as RecipeMessage
from cable_inspection.recipe.recipe import Recipe



class RecipeNode(Node, Recipe):
    """Main과 같은 프로세스에서 실행하며 HMI 수신부에 Recipe API를 제공한다."""



    # 기능: Recipe 저장소와 ROS 노드를 구성한다.
    #     system_path: 시스템 설정 JSON 경로.
    #     recipe_paths: 초기 레시피 JSON 경로 목록.
    #     반환: 없음.
    def __init__(self, system_path, recipe_paths=()):
        Recipe.__init__(self, system_path, recipe_paths)
        Node.__init__(self, "ccc_recipe_node")



    # 기능: 수신 ROS 레시피를 검증된 사전으로 변환한다.
    #     message: InspectionRecipe ROS 메시지.
    #     반환: 배열 순서를 보존한 레시피 사전. 원본 메시지는 변경하지 않는다.
    @staticmethod
    def decode_message(message):
        """수신 메시지를 검증된 실행 데이터로 변환한다. 접수 원본은 변경하지 않는다."""
        raw = message_to_ordereddict(message)
        Recipe.validate(raw)
        return raw



    # 기능: 레시피 사전을 검증하고 ROS 메시지로 변환한다.
    #     recipe: 전송할 레시피 사전.
    #     반환: 배열 순서를 보존한 InspectionRecipe ROS 메시지.
    @staticmethod
    def encode_message(recipe):
        """실행 순서를 보존한 ROS 레시피 메시지를 만든다."""
        Recipe.validate(recipe)
        message = RecipeMessage()
        set_message_fields(message, deepcopy(recipe))
        return message
