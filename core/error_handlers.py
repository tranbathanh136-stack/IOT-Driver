from flask import jsonify, request

def register_error_handlers(app):
    @app.errorhandler(404)
    def handle_404(e):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Resource not found", "status_code": 404}), 404
        return "<h3>404 - Trang không tồn tại</h3><p><a href='/'>Quay về Dashboard</a></p>", 404

    @app.errorhandler(500)
    def handle_500(e):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Internal server error", "status_code": 500}), 500
        return "<h3>500 - Lỗi máy chủ nội bộ</h3><p><a href='/'>Quay về Dashboard</a></p>", 500
