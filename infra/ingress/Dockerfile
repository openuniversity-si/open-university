# The webhook ingress alone (PORT5): the four standard-library modules it imports on the base image of Lambda, nothing
# else (no apt, no pip, no Origin CLI, no DBOS/SQLAlchemy/boto3). The deployer builds it on ARM from the repository
# root, like the service image, and records its URI in an SSM String parameter; the 40-port stack's IngressImage
# parameter names that parameter. The base image brings its own entrypoint and runtime interface client, which is why
# the stack drops its EntryPoint/WorkingDirectory override when IngressImage is not the service image.
FROM public.ecr.aws/lambda/python:3.12-arm64
COPY infra/ingress/__init__.py ${LAMBDA_TASK_ROOT}/tower_infra/__init__.py
COPY infra/service/tower_infra/ingress.py infra/service/tower_infra/awsjson.py infra/service/tower_infra/forge_webhooks.py \
     infra/service/tower_infra/ed25519.py ${LAMBDA_TASK_ROOT}/tower_infra/
ENV PYTHONDONTWRITEBYTECODE=0 PYTHONUNBUFFERED=1
CMD ["tower_infra.ingress.handler"]
