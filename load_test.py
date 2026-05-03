import asyncio
import time
import httpx

FACADE_URL = "http://127.0.0.1:8001"

REQUEST_TIMEOUT = httpx.Timeout(
    connect=10.0,
    read=300.0,
    write=30.0,
    pool=30.0,
)

LIMITS = httpx.Limits(
    max_connections=50,
    max_keepalive_connections=20,
)

PROGRESS_EVERY = 1000


async def send_transactions(client: httpx.AsyncClient, client_name: str, user_id: str, n: int):
    for i in range(1, n + 1):
        response = await client.post(
            f"{FACADE_URL}/transactions",
            json={"user_id": user_id, "amount": 1},
        )

        response.raise_for_status()

        if i % PROGRESS_EVERY == 0:
            print(f"  {client_name}: sent {i}/{n}")


async def run_scenario(user_ids, n_per_user: int):
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, limits=LIMITS) as client:
        tasks = []

        for index, user_id in enumerate(user_ids, start=1):
            client_name = f"client{index}"
            tasks.append(
                asyncio.create_task(
                    send_transactions(client, client_name, user_id, n_per_user)
                )
            )

        start = time.perf_counter()
        await asyncio.gather(*tasks)
        end = time.perf_counter()

    total_time = end - start
    total_requests = len(user_ids) * n_per_user
    rps = total_requests / total_time

    return total_time, total_requests, rps


async def get_accounts():
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        response = await client.get(f"{FACADE_URL}/accounts")
        response.raise_for_status()
        return response.json().get("accounts", {})


async def wait_for_balance(user_id: str, expected_balance: float, timeout_seconds: int = 120):
    start = time.perf_counter()

    while True:
        accounts = await get_accounts()
        current_balance = accounts.get(user_id)

        if current_balance == expected_balance:
            return current_balance

        if time.perf_counter() - start > timeout_seconds:
            print(
                f"  WARNING: balance for {user_id} did not reach {expected_balance}. "
                f"Current balance: {current_balance}"
            )
            return current_balance

        await asyncio.sleep(1)


async def wait_for_all_balances(expected_balances: dict, timeout_seconds: int = 120):
    start = time.perf_counter()

    while True:
        accounts = await get_accounts()

        all_ready = True
        for user_id, expected_balance in expected_balances.items():
            if accounts.get(user_id) != expected_balance:
                all_ready = False
                break

        if all_ready:
            return accounts

        if time.perf_counter() - start > timeout_seconds:
            print("  WARNING: not all balances reached expected values.")
            return accounts

        await asyncio.sleep(1)


async def reset_timing():
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        response = await client.post(f"{FACADE_URL}/timing/reset")
        response.raise_for_status()


async def get_timing():
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        response = await client.get(f"{FACADE_URL}/timing")
        response.raise_for_status()
        return response.json()


def print_timing_summary(timing: dict):
    logging_time = timing.get("total_logging_time_seconds", 0.0)
    counter_time = timing.get("total_counter_time_seconds", 0.0)
    measured_total = logging_time + counter_time

    print("  timing:", timing)

    if measured_total > 0:
        print(
            f"  logging contribution: {logging_time:.2f} s "
            f"({logging_time / measured_total * 100:.2f}%)"
        )
        print(
            f"  counter contribution: {counter_time:.2f} s "
            f"({counter_time / measured_total * 100:.2f}%)"
        )


async def main():
    print("Starting load test...")

    # Scenario 1: 10 accounts, 10k transactions per account
    users1 = [f"user{i}" for i in range(1, 11)]
    expected1 = {user_id: 10_000.0 for user_id in users1}

    print("\nScenario 1: 10 users, 10k tx per user")
    await reset_timing()

    t1, n1, rps1 = await run_scenario(users1, 10_000)

    print("  Waiting for counter-service to process queue...")
    accounts1 = await wait_for_all_balances(expected1)

    timing1 = await get_timing()

    print(f"  total_time = {t1:.2f} s, requests = {n1}, rps = {rps1:.2f}")
    print("  final_balances:")
    for user_id in users1:
        print(f"    {user_id}: {accounts1.get(user_id)}")

    print_timing_summary(timing1)

    # Scenario 2: 10 clients, same account, 10k transactions each
    same_user = "same_user"
    users2 = [same_user] * 10

    print("\nScenario 2: 10 clients, 10k tx each, same user")
    await reset_timing()

    t2, n2, rps2 = await run_scenario(users2, 10_000)

    print("  Waiting for counter-service to process queue...")
    final_balance2 = await wait_for_balance(same_user, 100_000.0)

    timing2 = await get_timing()

    print(f"  total_time = {t2:.2f} s, requests = {n2}, rps = {rps2:.2f}")
    print(f"  final_balance for {same_user}: {final_balance2}")

    print_timing_summary(timing2)


if __name__ == "__main__":
    asyncio.run(main())