import asyncio
import time
import httpx

FACADE_URL = "http://127.0.0.1:8001"


async def send_transactions(user_id: str, n: int):
    async with httpx.AsyncClient() as client:
        for _ in range(n):
            await client.post(
                f"{FACADE_URL}/transactions",
                json={"user_id": user_id, "amount": 1},
            )


async def run_scenario(users, n_per_user: int):
    tasks = [asyncio.create_task(send_transactions(u, n_per_user)) for u in users]
    start = time.perf_counter()
    await asyncio.gather(*tasks)
    end = time.perf_counter()
    total_time = end - start
    total_requests = len(users) * n_per_user
    rps = total_requests / total_time
    return total_time, total_requests, rps


async def get_balance(user_id: str):
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{FACADE_URL}/user/{user_id}")
        return resp.json().get("balance")


async def get_accounts():
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{FACADE_URL}/accounts")
        return resp.json().get("accounts", {})


async def reset_timing():
    async with httpx.AsyncClient() as client:
        await client.post(f"{FACADE_URL}/timing/reset")


async def get_timing():
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{FACADE_URL}/timing")
        return resp.json()


async def main():
    users1 = [f"user{i}" for i in range(1, 11)]
    await reset_timing()
    t1, n1, rps1 = await run_scenario(users1, 10_000)
    timing1 = await get_timing()
    accounts1 = await get_accounts()

    print("Scenario 1: 10 users, 10k tx per user")
    print(f"  total_time = {t1:.2f} s, requests = {n1}, rps = {rps1:.2f}")
    print("  final_balances (should all be 10000):")
    for u in users1:
        print(f"    {u}: {accounts1.get(u)}")
    print("  timing:", timing1)

    user = "same_user"
    users2 = [user] * 10
    await reset_timing()
    t2, n2, rps2 = await run_scenario(users2, 10_000)
    timing2 = await get_timing()
    balance2 = await get_balance(user)

    print("\nScenario 2: 10 clients, 10k tx each, same user")
    print(f"  total_time = {t2:.2f} s, requests = {n2}, rps = {rps2:.2f}")
    print(f"  final_balance for {user} (should be 100000): {balance2}")
    print("  timing:", timing2)


if __name__ == "__main__":
    asyncio.run(main())
