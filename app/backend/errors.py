class AppError(Exception):
    def __init__(self, message, code='invalid', status=400):
        super().__init__(message)
        self.message, self.code, self.status = message, code, status


def conflict(message='内容已被另一页面修改，请重新读取后再保存'):
    return AppError(message, 'conflict', 409)
