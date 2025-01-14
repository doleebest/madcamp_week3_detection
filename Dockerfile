# Step 1: Use an official Python runtime as a parent image
FROM python:3.12-slim

# Step 2: Set the working directory in the container
WORKDIR /app

# Step 3: Install required system packages
RUN apt-get update && apt-get install -y python3-distutils

# Step 4: Copy the current directory contents into the container
COPY . /app

# Step 5: Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Step 6: Expose the port that the app runs on
EXPOSE 5001

# Step 7: Define the command to run the application
CMD ["python", "test.py"]
