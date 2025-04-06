<<<<<<< HEAD
# Use an official Python runtime as a parent image
FROM python:3.11.8-alpine3.21


# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container at /app
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
# Use --no-cache-dir to reduce image size
RUN pip install --no-cache-dir -r requirements.txt --upgrade

# Copy the rest of the application code into the container at /app
COPY . .

# Define the command to run the application
CMD ["python", "main.py"]
=======
# Use an official Python runtime as a parent image
FROM python:3.11.5-alpine3.18

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container at /app
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
# Use --no-cache-dir to reduce image size
RUN pip install --no-cache-dir -r requirements.txt --upgrade

# Copy the rest of the application code into the container at /app
COPY . .

# Define the command to run the application
CMD ["python", "main.py"]
>>>>>>> 4ba1e3dd0dd17897e7ffe87c4e1453cbe23c5d0d
