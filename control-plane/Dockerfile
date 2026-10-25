# One image, three entrypoints: blufire-api (port 8000), blufire-mcp (port 8080), blufire-worker <job>.
FROM python:3.12-slim AS build
WORKDIR /src
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir --prefix=/install .

FROM python:3.12-slim
COPY --from=build /install /usr/local
RUN useradd --uid 10001 --no-create-home blufire
USER 10001
EXPOSE 8000 8080
CMD ["blufire-api"]
