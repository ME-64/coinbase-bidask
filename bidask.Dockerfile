FROM python:3.10-buster
WORKDIR /code

COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# RUN echo $PWD
# RUN echo $(ls)
CMD ["python3", "/code/bidask.py"]
