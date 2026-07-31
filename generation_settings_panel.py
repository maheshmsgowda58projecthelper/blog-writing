from datetime import date

import streamlit as st

from generation_settings import GenerationSettings
from dataclasses import asdict


# --------------------------------------------------
# Initialize Session State
# --------------------------------------------------

def initialize_generation_settings():

    if "generation_settings" not in st.session_state:

        st.session_state["generation_settings"] = (
            asdict(GenerationSettings())
        )

    if "generation_settings_open" not in st.session_state:

        st.session_state["generation_settings_open"] = False



# --------------------------------------------------
# Validate Settings
# --------------------------------------------------

def validate_generation_settings(settings):

    errors = []

    checks = [

        ("Search Queries", settings["min_queries"], settings["max_queries"], 1),

        ("Results Per Query", settings["min_results"], settings["max_results"], 1),

        ("Sections", settings["min_sections"], settings["max_sections"], 1),

        ("Bullet Points", settings["min_bullets"], settings["max_bullets"], 1),

        ("Target Words", settings["min_words"], settings["max_words"], 20),

        ("Maximum Images", settings["min_images"], settings["max_images"], 0),

    ]

    for name, minimum, maximum, lower_limit in checks:

        if minimum < lower_limit:

            errors.append(
                f"• {name}: Minimum must be at least {lower_limit}."
            )

        if maximum < minimum:

            errors.append(
                f"• {name}: Maximum must be greater than or equal to Minimum."
            )

    if settings["as_of_date"] > date.today():

        errors.append(
            "• As-of Date cannot be in the future."
        )

    return errors



# --------------------------------------------------
# Render Panel
# --------------------------------------------------

def render_generation_settings_panel():

    initialize_generation_settings()

    settings = dict(
        st.session_state["generation_settings"]
    )

    # ----------------------------------
    # Generation Settings Toggle
    # ----------------------------------

    if st.button(
        "⚙️ Generation Settings ▼"
        if not st.session_state["generation_settings_open"]
        else
        "⚙️ Generation Settings ▲",
        width="stretch",
    ):

        st.session_state["generation_settings_open"] = (
            not st.session_state["generation_settings_open"]
        )

        st.rerun()
        
        st.divider()

        st.markdown("### 📋 Current Configuration")

        st.info(
            f"""
            Research Mode : {settings['research_mode'].title()}

            As-of Date : {settings['as_of_date']}

            Queries : {settings['min_queries']} → {settings['max_queries']}

            Results : {settings['min_results']} → {settings['max_results']}

            Sections : {settings['min_sections']} → {settings['max_sections']}

            Bullets : {settings['min_bullets']} → {settings['max_bullets']}

            Words : {settings['min_words']} → {settings['max_words']}

            Images : {settings['min_images']} → {settings['max_images']}
        """
        )

    if st.session_state["generation_settings_open"]:

        st.markdown("### Research Mode")

        settings["research_mode"] = st.radio(

            label="Research Mode",
            label_visibility="collapsed",

            options=[
                "auto",
                "local",
                "hybrid",
                "web",
            ],

            format_func=lambda x: {
                "auto": "Auto (Recommended)",
                "local": "Local",
                "hybrid": "Hybrid",
                "web": "Web",
            }[x],

            index=[
                "auto",
                "local",
                "hybrid",
                "web",
            ].index(
                settings["research_mode"]
            ),
        )

        st.divider()

        st.markdown("### 📅 As-of Date")

        selected_date = st.date_input(

            "Search information available up to",

            value=settings["as_of_date"],
            

            max_value=date.today(),
        )

        settings["as_of_date"] = selected_date
        
        # Maximum Search Queries
        st.divider()

        st.markdown("### 🔎 Maximum Search Queries")

        c1, c2 = st.columns(2)

        with c1:

            settings["min_queries"] = st.number_input(
                "Minimum",
                min_value=1,
                value=settings["min_queries"],
                step=1,
            )

        with c2:

            settings["max_queries"] = st.number_input(
                "Maximum",
                min_value=1,
                value=settings["max_queries"],
                step=1,
            )
    
        # Results Per Query

        st.divider()

        st.markdown("### 📄 Results Per Query")

        c1, c2 = st.columns(2)

        with c1:

            settings["min_results"] = st.number_input(
                "Minimum ",
                min_value=1,
                value=settings["min_results"],
                step=1,
            )

        with c2:

            settings["max_results"] = st.number_input(
                "Maximum ",
                min_value=1,
                value=settings["max_results"],
                step=1,
            )
    
        # Sections

        st.divider()

        st.markdown("### 🧩 Sections (Tasks)")

        c1, c2 = st.columns(2)

        with c1:

            settings["min_sections"] = st.number_input(
                "Minimum  ",
                min_value=1,
                value=settings["min_sections"],
                step=1,
            )

        with c2:

            settings["max_sections"] = st.number_input(
                "Maximum  ",
                min_value=1,
                value=settings["max_sections"],
                step=1,
            )
    
        # Bullet Points

        st.divider()

        st.markdown("### 📌 Bullet Points Per Section")

        c1, c2 = st.columns(2)

        with c1:

            settings["min_bullets"] = st.number_input(
                "Minimum   ",
                min_value=1,
                value=settings["min_bullets"],
                step=1,
            )

        with c2:

            settings["max_bullets"] = st.number_input(
                "Maximum   ",
                min_value=1,
                value=settings["max_bullets"],
                step=1,
            )
    
        # Target Words
        st.divider()

        st.markdown("### 📝 Target Words")

        c1, c2 = st.columns(2)

        with c1:

            settings["min_words"] = st.number_input(
                "Minimum    ",
                min_value=20,
                value=settings["min_words"],
                step=10,
        )

        with c2:

            settings["max_words"] = st.number_input(
                "Maximum    ",
                min_value=20,
                value=settings["max_words"],
                step=10,
            )
    
        # Images

        st.divider()

        st.markdown("### 🖼 Maximum Images")

        c1, c2 = st.columns(2)

        with c1:

            settings["min_images"] = st.number_input(
                "Minimum     ",
                min_value=0,
                value=settings["min_images"],
                step=1,
            )

        with c2:

            settings["max_images"] = st.number_input(
                "Maximum     ",
                min_value=0,
                value=settings["max_images"],
                step=1,
            )
        
        # Apply / Reset Buttons
        
        st.divider()

        c1, c2 = st.columns(2)

        with c1:

            reset_clicked = st.button(
                "↺ Reset",
                width="stretch",
                key="generation_settings_reset",
            )

        with c2:

            apply_clicked = st.button(
                "✅ Apply",
                width="stretch",
                key="generation_settings_apply",
            )


        if reset_clicked:

            defaults = GenerationSettings()



            st.session_state["generation_settings"] = (
                asdict(defaults)
            )

            st.session_state["generation_settings_open"] = False

            st.success(
                "Generation settings reset."
            )

            st.rerun()
    
        if apply_clicked:

            errors = validate_generation_settings(settings)

            if errors:

                st.error(
                    "Please fix the following:\n\n"
                    + "\n".join(errors)
                )


            else:

                st.session_state[
                    "generation_settings"
                ] = settings

                st.session_state[
                    "generation_settings_open"
                ] = False

                st.success(
                    "Generation settings applied."
                )

                st.rerun()
        

    return st.session_state["generation_settings"]