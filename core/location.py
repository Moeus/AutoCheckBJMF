import random
import re


def modify_decimal_part(num: float | str) -> float:
    """
    对经纬度小数部分的第 4~8 位施加随机偏移。
    """
    num = float(num)
    num_str = f"{num:.8f}"
    decimal_index = num_str.find(".")
    decimal_part = num_str[decimal_index + 4: decimal_index + 9]
    decimal_value = int(decimal_part)
    random_offset = random.randint(-15000, 15000)
    new_decimal_value = abs(decimal_value + random_offset)
    new_decimal_str = f"{new_decimal_value:05d}"
    new_num_str = num_str[:decimal_index + 4] + new_decimal_str + num_str[decimal_index + 9:]
    return float(new_num_str)


def pick_location(locations: list) -> dict:
    """从定位点列表中随机选取一个定位点。"""
    return random.choice(locations)


def is_valid_coordinate(value: str, min_value: float, max_value: float) -> bool:
    """校验单个经纬度值，要求至少 4 位小数并落在合法范围内。"""
    if not re.match(r"^-?\d+\.\d{4,}$", value):
        return False
    try:
        number = float(value)
    except ValueError:
        return False
    return min_value <= number <= max_value


def parse_coordinate_pair(value: str) -> tuple[str, str] | None:
    """
    解析从地图工具直接复制的经纬度文本，返回 (lat, lng)。
    """
    numbers = re.findall(r"-?\d+(?:\.\d+)?", value)
    if len(numbers) < 2:
        return None

    lat, lng = numbers[0], numbers[1]
    if not is_valid_coordinate(lat, -90, 90):
        return None
    if not is_valid_coordinate(lng, -180, 180):
        return None

    return lat, lng


def format_location(lat: float, lng: float, acc: str) -> str:
    """格式化签到使用的位置。"""
    return f"纬度 {float(lat):.6f}，经度 {float(lng):.6f}，精度/海拔 {acc}"
