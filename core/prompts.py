import questionary


def confirm_or_default(message: str, default: bool) -> bool:
    """
    questionary 在部分终端或取消输入时可能返回 None。
    这里将 None 按默认值处理，避免默认保存提示被误判为不保存。
    """
    answer = questionary.confirm(message, default=default).ask()
    return default if answer is None else answer
