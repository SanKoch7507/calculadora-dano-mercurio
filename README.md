# ⚖️ Calculadora Pericial de Valoração do Dano por Mercúrio (Hg⁰)

Simulador pericial econométrico e toxicológico para quantificação do passivo socioambiental e de saúde pública decorrente do fornecimento, comercialização ou depósito ilegal de mercúrio destinado ao garimpo ilegal de ouro na Amazônia.

## 🔬 Metodologia Científica e Espelhamento Oficial

Calibrado com **100% de precisão** aos resultados monetários e não-monetários da **Calculadora de Impactos do Garimpo (CSF / MPF / ENSP-Fiocruz)** (`https://miningcalculator.conservation-strategy.org/calculator`), seguindo a diretriz técnica recomendada pelos desenvolvedores da ferramenta para apreensões/vendas de mercúrio:
- **Unidade de Análise (`Quantidade de Ouro`):** conversão na razão padrão da CSF para o Brasil de **2,60 kg de Hg para cada 1,00 kg de ouro extraído** ($M_{Au} = M_{Hg} / 2,60$).
- **Cenário Conservador (`Com Uso de Retorta`):** aluvião, cava de 2,5 m de profundidade média, dispersão de 13% nos corpos hídricos, 8,8% no solo e 33% na atmosfera.
- **Integração de APIs em Tempo Real:** consulta direta à PTAX do **Banco Central do Brasil (Olinda)**, inflação acumulada do **Banco Mundial** (base 2022) e cotação internacional do ouro (**GoldAPI.io / MetalpriceAPI / XAU Spot**).

## 🚀 Como Executar

```bash
pip install -r requirements.txt
streamlit run app.py
```
