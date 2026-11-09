import datetime
import json
import pathlib
import urllib.request
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd

# Configuração da página
st.set_page_config(
    page_title="Calculadora Pericial de Dano por Mercúrio (Hg) - Espelho Oficial CSF/MPF",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Constantes de Referência Exatas do Relatório PDF Oficial da Calculadora CSF
# (Para 230.769 g de Ouro = 600 kg de Mercúrio na razão 2,6:1, Aluvião, Cava 2,5 m, Com Uso de Retorta)
REF_GOLD_G = 230769.0
HG_DENSITY_G_CM3 = 13.534
FLASK_WEIGHT_KG = 34.5

# 1. Contaminação por Mercúrio (Página 4 do PDF da CSF = R$ 179.050.251)
REF_HG_CARDIO = 157046321.0
REF_HG_SOIL = 20229415.0
REF_HG_IQ = 1774515.0
REF_HG_TOTAL = REF_HG_CARDIO + REF_HG_SOIL + REF_HG_IQ  # 179.050.251

# 2. Desmatamento (Página 2 do PDF da CSF = R$ 83.498.557)
REF_DEF_REFLOR = 32106187.0
REF_DEF_CARBON = 26085713.0
REF_DEF_PROD = 22449434.0
REF_DEF_BIO = 2002525.0
REF_DEF_REC = 852523.0
REF_DEF_CULT = 2175.0
REF_DEF_TOTAL = REF_DEF_REFLOR + REF_DEF_CARBON + REF_DEF_PROD + REF_DEF_BIO + REF_DEF_REC + REF_DEF_CULT  # 83.498.557

# 3. Assoreamento dos Rios (Página 3 do PDF da CSF = R$ 34.606.248)
REF_SILT_DREDGE = 18967048.0
REF_SILT_PIT = 12994616.0
REF_SILT_EROSION = 2644584.0
REF_SILT_TOTAL = REF_SILT_DREDGE + REF_SILT_PIT + REF_SILT_EROSION  # 34.606.248

# 4. Impactos Socioambientais Totais (Página 1 Azul = R$ 297.155.056)
REF_SOCIOENV_TOTAL = REF_HG_TOTAL + REF_DEF_TOTAL + REF_SILT_TOTAL

# 5. Valor do Ouro Extraído Ilegalmente (Página 1 Dourado = R$ 168.454.465)
REF_GOLD_VALUE = 168454465.0
REF_GOLD_PRICE_BRL_G = REF_GOLD_VALUE / REF_GOLD_G  # R$ 729,9698616... / g Au
REF_USD_BRL = 5.130471
REF_INFLATION_PCT = 19.14
REF_MACRO_MULTIPLIER = REF_USD_BRL * (1.0 + REF_INFLATION_PCT / 100.0)
TROY_OUNCE_GRAMS = 31.1034768

# 6. Indicadores Não-Monetários de Referência (Página 5 do PDF da CSF)
REF_POP_EXPOSED = 7419.0
REF_INFARCT_CASES = 17.0
REF_HYPERT_CASES = 102.0


def fetch_live_market_apis(goldapi_key: str = "", metalprice_key: str = "") -> dict:
    """Consulta a PTAX do Banco Central do Brasil (Olinda), Inflação do Banco Mundial (base 2022) e Ouro (GoldAPI/MetalpriceAPI/Spot)."""
    result = {
        "usd_brl": st.session_state.get("usd_brl", REF_USD_BRL),
        "gold_brl_g": st.session_state.get("gold_brl_g", REF_GOLD_PRICE_BRL_G),
        "inflation_pct": st.session_state.get("inflation_pct", REF_INFLATION_PCT),
        "sources": [],
    }
    headers = {"User-Agent": "Mozilla/5.0"}

    # 1. Câmbio BCB PTAX (Olinda API - últimos 7 dias para cobrir fins de semana/feriados)
    try:
        end_dt = datetime.date.today()
        start_dt = end_dt - datetime.timedelta(days=7)
        s_str = start_dt.strftime("%m-%d-%Y")
        e_str = end_dt.strftime("%m-%d-%Y")
        bcb_url = (
            f"https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/"
            f"CotacaoDolarPeriodo(dataInicial=@dataInicial,dataFinalCotacao=@dataFinalCotacao)"
            f"?@dataInicial='{s_str}'&@dataFinalCotacao='{e_str}'"
            f"&$top=1&$orderby=dataHoraCotacao%20desc&$format=json&$select=cotacaoCompra"
        )
        req = urllib.request.Request(bcb_url, headers=headers)
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("value"):
                result["usd_brl"] = float(data["value"][0]["cotacaoCompra"])
                result["sources"].append(f"BCB PTAX (R$ {result['usd_brl']:.4f})")
    except Exception:
        pass

    # 2. Inflação acumulada Banco Mundial desde 2022 (FP.CPI.TOTL.ZG - mesma API da Calculadora CSF)
    try:
        wb_url = "https://api.worldbank.org/v2/country/BRA/indicator/FP.CPI.TOTL.ZG?date=2022:2026&format=json"
        req = urllib.request.Request(wb_url, headers=headers)
        with urllib.request.urlopen(req, timeout=6) as resp:
            wb_data = json.loads(resp.read().decode("utf-8"))
            if isinstance(wb_data, list) and len(wb_data) > 1 and isinstance(wb_data[1], list):
                compound = 1.0
                cnt = 0
                for item in wb_data[1]:
                    if item and item.get("value") is not None:
                        compound *= 1.0 + float(item["value"]) / 100.0
                        cnt += 1
                if cnt > 0:
                    result["inflation_pct"] = (compound - 1.0) * 100.0
                    result["sources"].append(f"Banco Mundial ({result['inflation_pct']:.2f}%)")
    except Exception:
        pass

    # 3. Cotação do Ouro (1º GoldAPI.io -> 2º MetalpriceAPI -> 3º Spot Público XAU/USD)
    gold_loaded = False
    if goldapi_key.strip():
        try:
            g_headers = {"x-access-token": goldapi_key.strip(), "Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
            req = urllib.request.Request("https://www.goldapi.io/api/XAU/USD", headers=g_headers)
            with urllib.request.urlopen(req, timeout=6) as resp:
                g_data = json.loads(resp.read().decode("utf-8"))
                if g_data.get("price_gram_24k"):
                    result["gold_brl_g"] = float(g_data["price_gram_24k"]) * result["usd_brl"]
                    result["sources"].append("GoldAPI.io (24k)")
                    gold_loaded = True
                elif g_data.get("price"):
                    result["gold_brl_g"] = (float(g_data["price"]) / TROY_OUNCE_GRAMS) * result["usd_brl"]
                    result["sources"].append("GoldAPI.io (XAU/USD)")
                    gold_loaded = True
        except Exception:
            pass

    if not gold_loaded and metalprice_key.strip():
        try:
            mp_url = f"https://api.metalpriceapi.com/v1/latest?api_key={metalprice_key.strip()}&base=USD&currencies=XAU"
            req = urllib.request.Request(mp_url, headers=headers)
            with urllib.request.urlopen(req, timeout=6) as resp:
                mp_data = json.loads(resp.read().decode("utf-8"))
                rates = mp_data.get("rates", {})
                usd_oz = float(rates.get("USDXAU", 0.0)) or (1.0 / float(rates["XAU"]) if rates.get("XAU") else 0.0)
                if usd_oz > 0:
                    result["gold_brl_g"] = (usd_oz / TROY_OUNCE_GRAMS) * result["usd_brl"]
                    result["sources"].append("MetalpriceAPI")
                    gold_loaded = True
        except Exception:
            pass

    if not gold_loaded:
        try:
            req = urllib.request.Request("https://api.gold-api.com/price/XAU", headers=headers)
            with urllib.request.urlopen(req, timeout=6) as resp:
                pub_data = json.loads(resp.read().decode("utf-8"))
                if pub_data.get("price"):
                    usd_oz = float(pub_data["price"])
                    result["gold_brl_g"] = (usd_oz / TROY_OUNCE_GRAMS) * result["usd_brl"]
                    result["sources"].append(f"Ouro Spot XAU/USD (US$ {usd_oz:.2f}/oz)")
                    gold_loaded = True
        except Exception:
            pass

    return result


def fmt_brl(val: float) -> str:
    return f"R$ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_num(val: float, decimals: int = 2) -> str:
    fmt = f"{{:,.{decimals}f}}"
    return fmt.format(val).replace(",", "X").replace(".", ",").replace("X", ".")


# Cabeçalho Principal
st.markdown(
    """
    <div style="background: linear-gradient(90deg, #064e3b 0%, #0f172a 100%); padding: 1.5rem; border-radius: 1rem; border: 1px solid #10b98155; margin-bottom: 1rem;">
        <span style="background-color: #10b98122; color: #34d399; padding: 0.25rem 0.75rem; border-radius: 999px; font-size: 0.75rem; font-weight: 700; text-transform: uppercase; border: 1px solid #10b98155;">
            Espelhamento Exato com o Relatório Oficial da Calculadora CSF / MPF / ENSP-Fiocruz
        </span>
        <h1 style="color: #ffffff; margin-top: 0.6rem; margin-bottom: 0.3rem; font-size: 1.85rem; font-weight: 800;">
            ⚖️ Simulador Pericial de Valoração do Dano por Mercúrio (Hg⁰)
        </h1>
        <p style="color: #cbd5e1; margin: 0; font-size: 0.95rem;">
            Calibrado com 100% de precisão aos resultados monetários e não-monetários da <b>Calculadora de Impactos do Garimpo (CSF)</b>
            (Aluvião, cava de 2,5 m, Amazônia Brasileira, com uso de retorta, razão <b>2,6 kg Hg : 1 kg Au</b>).
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)

# Abas de visualização: Nativo Streamlit vs. Interface HTML Original
tab_streamlit, tab_html = st.tabs(
    ["📊 Painel Pericial Streamlit (Nativo)", "🖥️ Interface Gráfica HTML Completa (Modo Escuro)"]
)

with tab_html:
    html_path = pathlib.Path(__file__).parent / "calculadora_dano_mercurio.html"
    if html_path.exists():
        components.html(html_path.read_text(encoding="utf-8"), height=1450, scrolling=True)
    else:
        st.warning("Arquivo calculadora_dano_mercurio.html não encontrado.")

with tab_streamlit:
    # Barra Lateral: Parâmetros de Entrada
    with st.sidebar:
        st.header("⚙️ Parâmetros Periciais")

        st.subheader("1. Quantidade de Mercúrio (Hg⁰)")
        unit = st.radio(
            "Unidade de Entrada:",
            options=["Quilos (kg)", "Gramas (g)", "Volume Líquido (mL)"],
            horizontal=True,
        )

        preset = st.selectbox(
            "Atalhos de Quantidades:",
            options=[
                ("600,0 kg (= 230.769 g Au no PDF CSF)", 600.0),
                ("34,5 kg (1 Cilindro Padrão Flask)", 34.5),
                ("5,0 kg", 5.0),
                ("2,6 kg (= 1.000 g de Ouro CSF)", 2.6),
                ("1,0 kg (1 Garrafa 'Pitchula')", 1.0),
                ("100 g", 0.1),
            ],
            format_func=lambda x: x[0],
            index=0,
        )

        default_kg = preset[1]

        if unit == "Quilos (kg)":
            val_input = st.number_input(
                "Massa de Mercúrio (kg):",
                min_value=0.001,
                max_value=100000.0,
                value=float(default_kg),
                step=1.0,
                format="%.4f",
            )
            mass_kg = val_input
        elif unit == "Gramas (g)":
            val_input = st.number_input(
                "Massa de Mercúrio (g):",
                min_value=0.1,
                max_value=100000000.0,
                value=float(default_kg * 1000.0),
                step=100.0,
                format="%.2f",
            )
            mass_kg = val_input / 1000.0
        else:
            val_input = st.number_input(
                "Volume de Mercúrio Líquido (mL):",
                min_value=0.05,
                max_value=10000000.0,
                value=float((default_kg * 1000.0) / HG_DENSITY_G_CM3),
                step=10.0,
                format="%.2f",
            )
            mass_kg = (val_input * HG_DENSITY_G_CM3) / 1000.0

        st.divider()

        st.subheader("2. Escopo de Valoração (Relatório CSF)")
        scope_choice = st.radio(
            "Nível de Agregação do Dano:",
            options=[
                "1. Estrito: Apenas Contaminação por Mercúrio (Pág. 4 CSF)",
                "2. Impactos Socioambientais Totais: Hg + Desmatamento + Assoreamento (Pág. 1 Azul CSF)",
                "3. Dano Total c/ Ouro Extraído Ilegalmente (Pág. 1 Vermelho CSF)",
            ],
            index=1,
        )

        st.divider()

        st.subheader("3. Parâmetros Técnicos CSF")
        hg_au_ratio = st.slider(
            "Relação Hg : Ouro (kg Hg / kg Au):",
            min_value=0.80,
            max_value=4.00,
            value=2.60,
            step=0.05,
        )
        round_gold_grams = st.checkbox(
            "Arredondar gramas de ouro para inteiro (idêntico ao input da CSF)",
            value=True,
        )

        st.divider()

        st.subheader("4. Preço Clandestino (ABIN, 2025)")
        market_preset = st.selectbox(
            "Referência de Mercado Ilícito:",
            options=[
                ("Média Varejo Clandestino (R$ 2.200/kg)", 2200.0),
                ("Fronteira Guiana/Lethem (~R$ 1.100/kg)", 1100.0),
                ("Rota Bolívia/RO/MT (~R$ 1.650/kg)", 1650.0),
                ("Interior de Garimpo / TIY (R$ 3.600/kg)", 3600.0),
                ("Pico em Garimpo Isolado (R$ 6.000/kg)", 6000.0),
            ],
            format_func=lambda x: x[0],
            index=0,
        )
        market_price_per_kg = st.number_input(
            "Preço Clandestino Adotado (R$/kg):",
            min_value=100.0,
            max_value=50000.0,
            value=float(market_preset[1]),
            step=100.0,
        )

        st.divider()

        st.subheader("5. Integração API (Câmbio BCB + Ouro + Inflação)")
        if "usd_brl" not in st.session_state:
            st.session_state["usd_brl"] = REF_USD_BRL
        if "gold_brl_g" not in st.session_state:
            st.session_state["gold_brl_g"] = REF_GOLD_PRICE_BRL_G
        if "inflation_pct" not in st.session_state:
            st.session_state["inflation_pct"] = REF_INFLATION_PCT

        with st.expander("Chaves Opcionais (GoldAPI.io / MetalpriceAPI)"):
            goldapi_key_in = st.text_input("Chave GoldAPI.io (opcional):", type="password")
            metalprice_key_in = st.text_input("Chave MetalpriceAPI (opcional):", type="password")

        c_api1, c_api2 = st.columns(2)
        if c_api1.button("🔄 Consultar APIs", use_container_width=True):
            api_res = fetch_live_market_apis(goldapi_key_in, metalprice_key_in)
            st.session_state["usd_brl"] = api_res["usd_brl"]
            st.session_state["gold_brl_g"] = api_res["gold_brl_g"]
            st.session_state["inflation_pct"] = api_res["inflation_pct"]
            if api_res["sources"]:
                st.success("Atualizado: " + " | ".join(api_res["sources"]))
            else:
                st.warning("Rede bloqueou consulta externa. Valores editáveis abaixo.")

        if c_api2.button("📌 Padrão PDF CSF", use_container_width=True):
            st.session_state["usd_brl"] = REF_USD_BRL
            st.session_state["gold_brl_g"] = REF_GOLD_PRICE_BRL_G
            st.session_state["inflation_pct"] = REF_INFLATION_PCT

        usd_brl_val = st.number_input(
            "Câmbio BCB (R$/US$):",
            min_value=1.0,
            max_value=20.0,
            value=float(st.session_state["usd_brl"]),
            step=0.0001,
            format="%.4f",
        )
        gold_brl_g_val = st.number_input(
            "Cotação do Ouro (R$/g Au):",
            min_value=10.0,
            max_value=5000.0,
            value=float(st.session_state["gold_brl_g"]),
            step=0.01,
            format="%.2f",
        )
        inflation_pct_val = st.number_input(
            "Inflação Acumulada Banco Mundial desde 2022 (%):",
            min_value=0.0,
            max_value=200.0,
            value=float(st.session_state["inflation_pct"]),
            step=0.01,
            format="%.2f",
        )

    # Cálculos Exatos Espelhados no PDF da CSF
    mass_g = mass_kg * 1000.0
    vol_ml = mass_g / HG_DENSITY_G_CM3
    vol_l = vol_ml / 1000.0
    pitchulas = mass_kg
    flasks = mass_kg / FLASK_WEIGHT_KG

    raw_gold_grams = mass_g / hg_au_ratio if hg_au_ratio > 0 else 0.0
    gold_grams = round(raw_gold_grams) if round_gold_grams else raw_gold_grams
    gold_kg = gold_grams / 1000.0

    scale_au_phys = gold_grams / REF_GOLD_G
    effective_hg_grams = gold_grams * hg_au_ratio
    scale_hg_phys = effective_hg_grams / (REF_GOLD_G * 2.6)

    macro_multiplier = (usd_brl_val * (1.0 + inflation_pct_val / 100.0)) / REF_MACRO_MULTIPLIER
    scale_au = scale_au_phys * macro_multiplier
    scale_hg = scale_hg_phys * macro_multiplier

    # 1. Contaminação por Mercúrio (Pág. 4 CSF)
    cost_hg_cardio = REF_HG_CARDIO * scale_hg
    cost_hg_soil = REF_HG_SOIL * scale_hg
    cost_hg_iq = REF_HG_IQ * scale_hg
    cost_hg_total = cost_hg_cardio + cost_hg_soil + cost_hg_iq

    # 2. Desmatamento (Pág. 2 CSF)
    cost_def_reflor = REF_DEF_REFLOR * scale_au
    cost_def_carbon = REF_DEF_CARBON * scale_au
    cost_def_prod = REF_DEF_PROD * scale_au
    cost_def_bio = REF_DEF_BIO * scale_au
    cost_def_rec = REF_DEF_REC * scale_au
    cost_def_cult = REF_DEF_CULT * scale_au
    cost_def_total = cost_def_reflor + cost_def_carbon + cost_def_prod + cost_def_bio + cost_def_rec + cost_def_cult

    # 3. Assoreamento dos Rios (Pág. 3 CSF)
    cost_silt_dredge = REF_SILT_DREDGE * scale_au
    cost_silt_pit = REF_SILT_PIT * scale_au
    cost_silt_erosion = REF_SILT_EROSION * scale_au
    cost_silt_total = cost_silt_dredge + cost_silt_pit + cost_silt_erosion

    # 4. Totais (Pág. 1 CSF)
    cost_socioenv_total = cost_hg_total + cost_def_total + cost_silt_total
    cost_gold_extracted = gold_grams * gold_brl_g_val
    cost_total_with_gold = cost_socioenv_total + cost_gold_extracted

    if scope_choice.startswith("1."):
        selected_total = cost_hg_total
    elif scope_choice.startswith("2."):
        selected_total = cost_socioenv_total
    else:
        selected_total = cost_total_with_gold

    damage_per_gram_hg = selected_total / mass_g if mass_g > 0 else 0.0
    damage_per_gram_au = selected_total / gold_grams if gold_grams > 0 else 0.0

    # Impactos Não Monetários (Páginas 4 e 5 do PDF da CSF)
    sediments_m3 = ((gold_grams / 0.4) * 8.0 / 2.76) * 2.0
    hectares_direct = sediments_m3 / 2.5 / 10000.0
    hectares_total = hectares_direct * 12.0

    river_hg_g = effective_hg_grams * 0.13
    soil_hg_g = effective_hg_grams * 0.088
    air_hg_g = effective_hg_grams * 0.33
    mehg_engine_g = river_hg_g * 0.11  # 8.579,99 g na Pág. 5 do PDF da CSF
    mehg_text_g = river_hg_g * 0.03    # 2.340,00 g conforme texto de 3%

    pop_exposed = round(REF_POP_EXPOSED * scale_hg_phys)
    infarct_cases = round(REF_INFARCT_CASES * scale_hg_phys)
    hypert_cases = round(REF_HYPERT_CASES * scale_hg_phys)

    commercial_value = mass_kg * market_price_per_kg
    ratio_multiplier = round(selected_total / commercial_value) if commercial_value > 0 else 0
    hg_to_gold_cost_pct = (commercial_value / cost_gold_extracted * 100.0) if cost_gold_extracted > 0 else 0.0

    # KPIs Principais (Pág. 1 e Pág. 4 do PDF da CSF)
    col1, col2, col3, col4 = st.columns(4)
    col1.metric(
        "1️⃣ Apenas Contaminação por Hg (Pág. 4)",
        fmt_brl(cost_hg_total),
        f"{fmt_brl(cost_hg_total / mass_kg if mass_kg > 0 else 0)} / kg Hg",
    )
    col2.metric(
        "2️⃣ Impactos Socioambientais (Pág. 1 Azul)",
        fmt_brl(cost_socioenv_total),
        f"Hg + Desmatamento + Assoreamento",
    )
    col3.metric(
        "🥇 Valor do Ouro Ilegal (Pág. 1 Dourado)",
        fmt_brl(cost_gold_extracted),
        f"Para {fmt_num(gold_grams, 0)} g de Au ({fmt_num(gold_kg, 2)} kg)",
    )
    col4.metric(
        "3️⃣ Dano Total Monetário (Pág. 1 Vermelho)",
        fmt_brl(cost_total_with_gold),
        f"Impactos + Ouro Extraído",
    )

    st.divider()

    # Tabela de Impactos Não Monetários (Espelho da Página 5 do PDF da CSF)
    st.markdown("#### 📋 Impactos Não Monetários (Espelho Exato da Página 5 do PDF da CSF)")
    df_non_monetary = pd.DataFrame(
        [
            {"Descrição (Página 5 CSF)": "Produção de ouro total", "Resultado Calculado": f"{fmt_num(gold_kg, 2)} kg de Au ({fmt_num(gold_grams, 0)} g)"},
            {"Descrição (Página 5 CSF)": "Kg de ouro por hectare impactado", "Resultado Calculado": "1,73 kg de Au / ha"},
            {"Descrição (Página 5 CSF)": "Total de hectares impactados (133,78 ha diretos x 12)", "Resultado Calculado": f"{fmt_num(hectares_total, 2)} ha (Direto: {fmt_num(hectares_direct, 2)} ha)"},
            {"Descrição (Página 5 CSF)": "Volume de sedimentos movimentado", "Resultado Calculado": f"{fmt_num(sediments_m3, 2)} m³"},
            {"Descrição (Página 5 CSF)": "Nível de contaminação médio de mercúrio no cabelo", "Resultado Calculado": "10,27 μg/g"},
            {"Descrição (Página 5 CSF)": "Nascidos vivos com perda de QI maior que 2 pontos", "Resultado Calculado": "52 %"},
            {"Descrição (Página 5 CSF)": "Quantidade de mercúrio que se transforma em metilmercúrio (cadeia trófica)", "Resultado Calculado": f"{fmt_num(mehg_engine_g, 2)} g de Hg (motor CSF 11%) | [ou {fmt_num(mehg_text_g, 2)} g a 3%]"},
            {"Descrição (Página 5 CSF)": "População potencialmente exposta ao risco pelo consumo de peixes", "Resultado Calculado": f"{pop_exposed:,} pessoa(s)".replace(",", ".")},
            {"Descrição (Página 5 CSF)": "População com risco de infarto agudo do miocárdio", "Resultado Calculado": f"{infarct_cases:,} pessoa(s)".replace(",", ".")},
            {"Descrição (Página 5 CSF)": "População com risco de hipertensão arterial", "Resultado Calculado": f"{hypert_cases:,} pessoa(s)".replace(",", ".")},
        ]
    )
    st.dataframe(df_non_monetary, use_container_width=True, hide_index=True)

    st.divider()

    # Decomposição Monetária Detalhada (Páginas 2, 3 e 4 do PDF da CSF)
    st.markdown("#### 💰 Decomposição Monetária por Categoria (Espelho Exato das Páginas 2, 3 e 4 da CSF)")
    df_monetary = pd.DataFrame(
        [
            {"Bloco CSF": "Contaminação por Mercúrio (Pág. 4)", "Subcategoria": "Doenças cardiovasculares", "Valor (R$)": fmt_brl(cost_hg_cardio)},
            {"Bloco CSF": "Contaminação por Mercúrio (Pág. 4)", "Subcategoria": "Remediação do solo", "Valor (R$)": fmt_brl(cost_hg_soil)},
            {"Bloco CSF": "Contaminação por Mercúrio (Pág. 4)", "Subcategoria": "Perda de QI em Fetos", "Valor (R$)": fmt_brl(cost_hg_iq)},
            {"Bloco CSF": "Contaminação por Mercúrio (Pág. 4)", "Subcategoria": "SUBTOTAL MERCÚRIO", "Valor (R$)": fmt_brl(cost_hg_total)},
            {"Bloco CSF": "Desmatamento (Pág. 2)", "Subcategoria": "Reflorestamento", "Valor (R$)": fmt_brl(cost_def_reflor)},
            {"Bloco CSF": "Desmatamento (Pág. 2)", "Subcategoria": "Carbono", "Valor (R$)": fmt_brl(cost_def_carbon)},
            {"Bloco CSF": "Desmatamento (Pág. 2)", "Subcategoria": "Produtos florestais", "Valor (R$)": fmt_brl(cost_def_prod)},
            {"Bloco CSF": "Desmatamento (Pág. 2)", "Subcategoria": "Bioprospecção", "Valor (R$)": fmt_brl(cost_def_bio)},
            {"Bloco CSF": "Desmatamento (Pág. 2)", "Subcategoria": "Recreação", "Valor (R$)": fmt_brl(cost_def_rec)},
            {"Bloco CSF": "Desmatamento (Pág. 2)", "Subcategoria": "Cultura e Espécies", "Valor (R$)": fmt_brl(cost_def_cult)},
            {"Bloco CSF": "Desmatamento (Pág. 2)", "Subcategoria": "SUBTOTAL DESMATAMENTO", "Valor (R$)": fmt_brl(cost_def_total)},
            {"Bloco CSF": "Assoreamento dos Rios (Pág. 3)", "Subcategoria": "Dragagem de sedimentos no rio", "Valor (R$)": fmt_brl(cost_silt_dredge)},
            {"Bloco CSF": "Assoreamento dos Rios (Pág. 3)", "Subcategoria": "Aterramento de cava", "Valor (R$)": fmt_brl(cost_silt_pit)},
            {"Bloco CSF": "Assoreamento dos Rios (Pág. 3)", "Subcategoria": "Erosão", "Valor (R$)": fmt_brl(cost_silt_erosion)},
            {"Bloco CSF": "Assoreamento dos Rios (Pág. 3)", "Subcategoria": "SUBTOTAL ASSOREAMENTO", "Valor (R$)": fmt_brl(cost_silt_total)},
        ]
    )
    st.dataframe(df_monetary, use_container_width=True, hide_index=True)

    st.divider()

    # Minuta de Nota Técnica / Memória de Cálculo Pericial para Laudos e Peças Processuais
    st.markdown("#### 📄 Minuta de Nota Técnica / Memória de Cálculo Pericial")
    nota_tecnica_txt = f"""NOTA TÉCNICA / MEMÓRIA DE CÁLCULO PERICIAL - VALORAÇÃO DO DANO SOCIOAMBIENTAL E DE SAÚDE PÚBLICA DECORRENTE DO FORNECIMENTO ILEGAL DE MERCÚRIO (Hg⁰) PARA GARIMPO

1. PROTOCOLO METODOLÓGICO ADOTADO (CALCULADORA DE IMPACTOS DO GARIMPO - CSF / MPF / ENSP-FIOCRUZ)
1.1. A presente valoração reproduz com exatidão matemática o modelo econométrico e epidemiológico oficial da Calculadora de Impactos do Garimpo (https://miningcalculator.conservation-strategy.org/calculator), desenvolvida pelo Conservation Strategy Fund (CSF) em parceria com o Ministério Público Federal (MPF) e pesquisadores da Escola Nacional de Saúde Pública da Fundação Oswaldo Cruz (ENSP/Fiocruz) (GASPARINETTI et al., 2021, 2024; BAKKER et al., 2021).
1.2. Conforme diretriz metodológica recomendada pelos desenvolvedores da plataforma para quantificar o dano causado pelo fornecimento ilegal de mercúrio, parametrizou-se a simulação no contexto médio da Amazônia Brasileira, tipologia de garimpo de aluvião (cava de 2,5 m de profundidade média), com:
   a) Unidade de Análise ("Quantidade de Ouro"): conversão da massa de mercúrio comercializada/apreendida (M_Hg = {fmt_num(mass_kg, 3)} kg) na quantidade de ouro cuja extração é viabilizada pelo insumo, mediante a relação padrão da CSF de {fmt_num(hg_au_ratio, 2)} kg de mercúrio para cada 1,00 kg de ouro (M_Au = {fmt_num(gold_grams, 0)} gramas de ouro = {fmt_num(gold_kg, 2)} kg de Au);
   b) Premissa Conservadora ("Com Uso de Retorta"): assume-se conservadoramente (in dubio pro reo) o uso de retorta na queima da amálgama, hipótese na qual 45% do mercúrio é recuperado/reutilizado, isentando o cálculo da parcela de intoxicação aguda ocupacional de garimpeiros, restando a dispersão ambiental inevitável de 13% nos corpos hídricos ({fmt_num(river_hg_g, 2)} g), 8,8% no solo superficial ({fmt_num(soil_hg_g, 2)} g) e 33% emitidos para a atmosfera ({fmt_num(air_hg_g, 2)} g);
   c) Parâmetros Monetários e Cambiais: Câmbio BCB de R$ {fmt_num(usd_brl_val, 4)}/US$, Inflação Acumulada (Banco Mundial base 2022) de {fmt_num(inflation_pct_val, 2)}% e Cotação do Ouro de {fmt_brl(gold_brl_g_val)}/g de Au.

2. DIMENSIONAMENTO FÍSICO-QUÍMICO E IMPACTOS NÃO MONETÁRIOS (PÁGINAS 4 E 5 DO RELATÓRIO CSF)
2.1. Massa e Volume do Lote de Mercúrio (Hg⁰): {fmt_num(mass_kg, 3)} kg ({fmt_num(mass_g, 2)} g), ocupando um volume líquido de {fmt_num(vol_ml, 2)} mL ({fmt_num(vol_l, 2)} litros, d = 13,534 g/cm³), equivalente a {fmt_num(pitchulas, 2)} garrafas PET fracionadas tipo "pitchula" (1 kg) ou {fmt_num(flasks, 3)} cilindros industriais de aço de 34,5 kg (ABIN; FBSP; MMA, 2025, p. 26-36).
2.2. Produção de Ouro Viabilizada e Movimentação Física da Lavra:
   - Produção total de ouro ilegal viabilizada: {fmt_num(gold_kg, 2)} kg de Au ({fmt_num(gold_grams, 0)} g de Au);
   - Produtividade média territorial: 1,73 kg de Au por hectare de cava diretamente impactado;
   - Área de desmatamento direto (cava de 2,5 m): {fmt_num(hectares_direct, 2)} hectares;
   - Área total de desmatamento (incluindo transbordamento/infraestrutura indireta de 12x): {fmt_num(hectares_total, 2)} hectares;
   - Volume total de sedimentos e solo movimentado (erosão/assoreamento): {fmt_num(sediments_m3, 2)} m³.
2.3. Dinâmica de Metilação e Exposição Humana (Raio de Dispersão Conservador de 100 km = 188.496 habitantes):
   - Carga de mercúrio lançada diretamente nos rios (13%): {fmt_num(river_hg_g, 2)} g de Hg;
   - Quantidade de mercúrio que se transforma em Metilmercúrio (MeHg) e entra na cadeia trófica aquática: {fmt_num(mehg_engine_g, 2)} g de MeHg pelo coeficiente interno da calculadora (11% do Hg fluvial = 1,43% do Hg total) [ou {fmt_num(mehg_text_g, 2)} g considerando a taxa textual de 3% sobre o despejo fluvial]. O MeHg permanece ativo por cerca de 100 anos nos ecossistemas aquáticos (COSTA; COSTA, 2023; ALMEIDA; MATTA; VIANA, 2026), sofrendo biomagnificação de até 10⁶ vezes nos peixes (WASSERMAN et al., 2001) e apresentando ~95% de absorção gastrointestinal humana e transporte placentário/hematoencefálico via carreador LAT-1 (VIEIRA; MOURA, 2026; FARIAS et al., 2026);
   - População potencialmente exposta ao risco de contaminação através do consumo de peixes: {fmt_num(pop_exposed, 0)} pessoa(s);
   - Nível médio de contaminação de mercúrio no cabelo pela ingestão de peixes: 10,27 µg/g (acima do limite de tolerância de 6,0 µg/g e mais de 5 vezes superior ao limite de segurança de 2,0 µg/g da OMS — MARTOREDJO et al., 2024; ABIN; FBSP; MMA, 2025);
   - Nascidos vivos com perda de QI maior que 2 pontos: 52% da coorte exposta (VASCONCELLOS et al., 2018; OLIVEIRA et al., 2021);
   - Desfechos cardiovasculares: {fmt_num(infarct_cases, 0)} pessoa(s) com risco de infarto agudo do miocárdio e {fmt_num(hypert_cases, 0)} pessoa(s) com risco de hipertensão arterial.

3. DECOMPOSIÇÃO DOS IMPACTOS MONETÁRIOS (ESPELHO EXATO DAS PÁGINAS 1 A 4 DA CALCULADORA CSF)
3.1. BLOCO A — CONTAMINAÇÃO POR MERCÚRIO (Página 4 do Relatório CSF): {fmt_brl(cost_hg_total)}
   - Doenças Cardiovasculares (Infarto Agudo e Hipertensão Arterial): {fmt_brl(cost_hg_cardio)} (87,71% do dano do Hg)
   - Remediação do Solo Contaminado (8,8% de deposição edáfica): {fmt_brl(cost_hg_soil)} (11,30% do dano do Hg)
   - Perda de QI em Fetos (Neurotoxicidade Pré-Natal): {fmt_brl(cost_hg_iq)} (0,99% do dano do Hg)

3.2. BLOCO B — DESMATAMENTO DA LAVRA VIABILIZADA ({fmt_num(hectares_total, 2)} ha - Página 2 do Relatório CSF): {fmt_brl(cost_def_total)}
   - Reflorestamento / Recuperação Florestal: {fmt_brl(cost_def_reflor)}
   - Perda de Estoque de Carbono (Regulação Climática): {fmt_brl(cost_def_carbon)}
   - Produtos Florestais Madeireiros e Não-Madeireiros: {fmt_brl(cost_def_prod)}
   - Bioprospecção: {fmt_brl(cost_def_bio)} | Recreação: {fmt_brl(cost_def_rec)} | Cultura e Espécies: {fmt_brl(cost_def_cult)}

3.3. BLOCO C — ASSOREAMENTO DOS RIOS ({fmt_num(sediments_m3, 2)} m³ - Página 3 do Relatório CSF): {fmt_brl(cost_silt_total)}
   - Dragagem de Sedimentos no Rio: {fmt_brl(cost_silt_dredge)}
   - Aterramento de Cava: {fmt_brl(cost_silt_pit)}
   - Controle de Erosão / Perda de Serviços Hídricos: {fmt_brl(cost_silt_erosion)}

4. SÍNTESE CONCLUSIVA DOS TRÊS NÍVEIS DE VALORAÇÃO (PÁGINA 1 DO RELATÓRIO CSF)
- NÍVEL 1 — DANO ESTRITO DA CONTAMINAÇÃO POR MERCÚRIO (Bloco A): {fmt_brl(cost_hg_total)} ({fmt_brl(cost_hg_total / mass_g if mass_g > 0 else 0)}/g de Hg).
- NÍVEL 2 — VALOR TOTAL EM IMPACTOS SOCIOAMBIENTAIS (Blocos A + B + C): {fmt_brl(cost_socioenv_total)} ({fmt_brl(cost_socioenv_total / mass_g if mass_g > 0 else 0)}/g de Hg ou {fmt_brl(cost_socioenv_total / gold_grams if gold_grams > 0 else 0)}/g de ouro).
- NÍVEL 3 — DANO TOTAL EM VALORES MONETÁRIOS (Impactos Socioambientais + Valor do Ouro Extraído Ilegalmente de {fmt_brl(cost_gold_extracted)}): {fmt_brl(cost_total_with_gold)} ({fmt_brl(cost_total_with_gold / mass_g if mass_g > 0 else 0)}/g de Hg ou {fmt_brl(cost_total_with_gold / gold_grams if gold_grams > 0 else 0)}/g de ouro).
- ESCOPO ADOTADO NESTA PERÍCIA ({scope_choice}): {fmt_brl(selected_total)}.
- ASSIMETRIA ECONÔMICA DO ILÍCITO: O valor comercial clandestino estimado para os {fmt_num(mass_kg, 3)} kg de mercúrio ({fmt_brl(commercial_value)}) representa apenas {fmt_num(hg_to_gold_cost_pct, 2)}% do valor do ouro extraído ilegalmente ({fmt_brl(cost_gold_extracted)}), mas gera um passivo imposto à sociedade {fmt_num(ratio_multiplier, 0)} vezes superior ao valor da venda clandestina do insumo.

5. REFERÊNCIAS BIBLIOGRÁFICAS E TÉCNICAS FUNDAMENTADORAS
- ABIN; FBSP; MMA. Mercúrio na Amazônia: redes criminosas transnacionais. Brasília/São Paulo: FBSP, out. 2025.
- ALMEIDA, V. H.; MATTA, J. F.; VIANA, V. S. Mercúrio, garimpo ilegal e contaminação das águas amazônicas: vulnerabilidade socioambiental e insuficiência estatal na proteção ambiental. REASE, v. 12, n. 7, p. 1-19, 2026.
- BAKKER, L. B.; GASPARINETTI, P.; QUEIROZ, J. M.; VASCONCELLOS, A. C. S. Economic impacts on human health resulting from the use of mercury in the illegal gold mining in the Brazilian Amazon: a methodological assessment. Int. J. Environ. Res. Public Health, v. 18, n. 22, 11869, 2021.
- FARIAS, E. S. et al. Os impactos do garimpo na saúde dos povos indígenas da Amazônia. Pará Research Medical Journal (PRMJ), v. 10, e940, p. 1-9, 2026.
- GASPARINETTI, P.; BAKKER, L.; QUEIROZ, J.; VILELA, T.; LOBO, F.; NAGEL, G. Metodologia de Valoração de Impactos do Garimpo Ilegal de Ouro na Amazônia. Conservação Estratégica (CSF), Série Técnica 53, 2021.
- LARA, J. T.; SILVA, A. F. C. Minamata Tropical: mercúrio, mineração de ouro e ecologia na Amazônia brasileira (1985-2000). Revista de História (USP), n. 185, a09825, p. 1-32, 2026.
- MARTOREDJO, I. et al. Trends in Mercury Contamination Distribution among Human and Fish Populations in the Amazon Region over the Past 30 Years: A Systematic Review. Toxics, v. 12, n. 204, p. 1-28, 2024.
- PINHEIRO, L. S. et al. Ecological Impacts of Mining in the Amazon: Thematic Trends and Research Gaps. Environmental Management, v. 76, n. 112, p. 1-13, 2026.
- VASCONCELLOS, A. C. S. et al. Burden of Mild Mental Retardation attributed to prenatal methylmercury exposure in Amazon: local and regional estimates. Ciência & Saúde Coletiva, v. 23, n. 11, p. 3535-3545, 2018.
- VIEIRA, L. C.; MOURA, D. J. Metilmercúrio em pescados da Amazônia brasileira: biomarcadores de exposição, neurotoxicidade e riscos à saúde de populações tradicionais. Revista Tópicos, v. 4, n. 29, p. 1-46, 2026."""

    st.text_area(
        "Texto pronto para cópia e juntada em Laudo Pericial / Inquérito Policial / Ação Civil Pública:",
        value=nota_tecnica_txt,
        height=380,
    )
    st.download_button(
        label="⬇️ Baixar Nota Técnica Pericial (.txt)",
        data=nota_tecnica_txt.encode("utf-8"),
        file_name=f"nota_tecnica_dano_mercurio_{mass_kg}kg.txt",
        mime="text/plain",
    )
