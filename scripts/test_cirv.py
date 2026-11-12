from methodology.cirv import (
    calculate_cerf_component,
    calculate_final_cirv,
)

# Afghanistan values from our Excel baseline
inform_risk = 78
inform_severity = 92
early_warning = 67
food = 78.56
conflict = 70.75

cerf_component = calculate_cerf_component(
    early_warning,
    food,
    conflict
)

final_cirv = calculate_final_cirv(
    inform_risk,
    inform_severity,
    cerf_component
)

print(f"CERF Component: {cerf_component:.2f}")
print(f"Final CIRV: {final_cirv:.2f}")

print()
print("Excel expected:")
print("CERF Component: 73.26")
print("Final CIRV: 81.09")