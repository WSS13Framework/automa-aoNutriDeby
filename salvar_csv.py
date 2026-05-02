import os
csv_content = r"""cole aqui o conteúdo completo do CSV"""
with open('data/pacientes.csv', 'w', encoding='utf-8') as f:
    f.write(csv_content)
print("Arquivo salvo")
