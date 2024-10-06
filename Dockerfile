# Use the official Python image from the Docker Hub
FROM python:3.11-slim

# Set the working directory inside the container
WORKDIR /app

# Copy the requirements file into the container
COPY requirements.txt .

# Install the Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application code into the container
COPY . .

# Set environment variable to ensure that Python outputs everything to stdout
ENV PYTHONUNBUFFERED=1

# Command to run your script
CMD ["python", "soularr.py"]
