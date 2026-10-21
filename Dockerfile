# Recipe for the online version of the dashboard (used by Render, see render.yaml).
# It builds a small Linux machine with Python, installs the libraries,
# copies in the code and the cleaned data, and starts the app.
FROM python:3.14-slim

# Run the app as a normal user, not as admin (safer).
RUN useradd -m -u 1000 user
WORKDIR /app

# Install the libraries first, so this slow step is cached between rebuilds.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/
COPY data/clean_flights.parquet data/
USER user

# The hosting service tells the app which port to use in the PORT variable
# (7860 if it is not set). gunicorn runs 1 worker process by default, which
# fits in the free plan's 512 MB of memory.
# --chdir src lets "app:server" find src/app.py.
CMD gunicorn --chdir src --bind 0.0.0.0:${PORT:-7860} --timeout 60 app:server
