cmake_minimum_required(VERSION 3.8)
project(cable_interfaces)
find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/InspectionResult.msg"
  "msg/InspectionPose.msg"
  "msg/EntrySetting.msg"
  "msg/GripSetting.msg"
  "msg/PullSetting.msg"
  "msg/InspectionPoint.msg"
  "msg/InspectionRecipe.msg"
  "msg/RecipeInfo.msg"
  "srv/ListRecipes.srv"
  "srv/GetRecipe.srv"
  "srv/SaveRecipe.srv"
  "srv/StartInspection.srv"
  "srv/QueryResults.srv"

)
ament_export_dependencies(rosidl_default_runtime)
ament_package()
