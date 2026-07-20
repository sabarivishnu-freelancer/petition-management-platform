from app import app

# Firebase Functions Python HTTP entrypoint.
# The Firebase Functions framework will call this function with a Flask request object.
# We forward the request into the Flask app and return the Flask response.

def petition_function(request):
    with app.request_context(request.environ):
        return app.full_dispatch_request()
