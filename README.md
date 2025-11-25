# dsbd_hw1

This project follows the guidelines provided in the supplied .pdf

It is currently a **Work in Progress (WIP)**.

It is managed by Python, gRPC and PostgreSQL and it uses `docker-compose` to handle the containers (database, user_manager and data_collector). 
To start this small infrastructure, open a terminal window and run:

```
docker-compose up --build
```

Add a new user with:

```
curl -X POST http://localhost:5001/users \
-H "Content-Type: application/json" \
-d '{"email": "mario.rossi@example.com", "nome": "Mario", "cognome": "Rossi"}'
```

```
curl http://localhost:5001/users/mario.rossi@example.com
```