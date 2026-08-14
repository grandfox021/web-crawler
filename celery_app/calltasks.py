from tasks  import add, devide



result = add.delay(4, 6)
print("Task result:", result.get(timeout=10))

result = devide.delay(4, 6)
print("Task result:", result.get(timeout=10))